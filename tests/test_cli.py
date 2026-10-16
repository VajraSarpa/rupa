import io
import json

import pytest

from rupa.cli import EXIT_INPUT, EXIT_OK, EXIT_RENDER, EXIT_USAGE, main

DOC = "---\ntitle: T\n---\n\n## A\n\nBody text.\n"


def run(monkeypatch, capsys, argv, stdin=DOC):
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def test_html_from_stdin(tmp_path, monkeypatch, capsys):
    target = tmp_path / "out.html"
    code, out, _ = run(monkeypatch, capsys, ["-o", str(target)])
    assert code == EXIT_OK
    assert target.read_text().startswith("<!doctype html>")
    # stdout is one status line, never the document
    assert out.count("\n") == 1 and out.startswith("rupa: wrote")


def test_pdf_reports_pages(tmp_path, monkeypatch, capsys):
    target = tmp_path / "out.pdf"
    code, out, _ = run(monkeypatch, capsys, ["-o", str(target), "--json"])
    status = json.loads(out)
    assert code == EXIT_OK
    assert status["ok"] and status["format"] == "pdf" and status["pages"] >= 1
    assert target.read_bytes()[:5] == b"%PDF-"


def test_pdf_text_is_forced_black(tmp_path):
    from rupa.document import parse
    from rupa.render import to_html

    html = to_html(parse(DOC), target="pdf")
    assert "color: #000000 !important" in html


def test_unknown_extension_is_usage_error(tmp_path, monkeypatch, capsys):
    code, _, err = run(monkeypatch, capsys, ["-o", str(tmp_path / "out.docx")])
    assert code == EXIT_USAGE and "use --to" in err


def test_bad_input_exit_code(tmp_path, monkeypatch, capsys):
    code, _, err = run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html")], stdin="")
    assert code == EXIT_INPUT and "empty" in err


def test_unknown_theme_exit_code(tmp_path, monkeypatch, capsys):
    code, _, err = run(
        monkeypatch, capsys, ["-o", str(tmp_path / "o.html"), "--theme", "nope"]
    )
    assert code == EXIT_RENDER and "unknown theme" in err


@pytest.mark.parametrize("ext", ["pdf", "html"])
def test_remote_images_are_rejected(tmp_path, monkeypatch, capsys, ext):
    md = "## x\n\n![remote](https://example.com/a.png?d=secret)\n"
    out = str(tmp_path / f"o.{ext}")
    code, _, err = run(monkeypatch, capsys, ["-o", out], stdin=md)
    assert code == EXIT_INPUT and "example.com" in err


def _image_doc(tmp_path, src):
    from PIL import Image

    (tmp_path / "doc").mkdir()
    Image.new("RGB", (40, 20), "red").save(tmp_path / "doc" / "fig.png")
    Image.new("RGB", (40, 20)).save(tmp_path / "secret.png")
    md = tmp_path / "doc" / "t.md"
    md.write_text(f"## x\n\n![f]({src})\n")
    return str(md)


def test_relative_image_next_to_the_markdown_is_embedded(tmp_path, capsys):
    import pdfplumber

    target = tmp_path / "out" / "o.pdf"
    assert main([_image_doc(tmp_path, "fig.png"), "-o", str(target)]) == EXIT_OK
    with pdfplumber.open(target) as pdf:
        assert sum(len(p.images) for p in pdf.pages) == 1


@pytest.mark.parametrize("src", ["missing.png", "../secret.png"])
def test_missing_or_outside_image_fails_the_render(tmp_path, capsys, src):
    code = main([_image_doc(tmp_path, src), "-o", str(tmp_path / "o.pdf")])
    assert code == EXIT_RENDER and "resource" in capsys.readouterr().err


def test_to_flag_overrides_extension(tmp_path, monkeypatch, capsys):
    target = tmp_path / "report.out"
    code, _, _ = run(monkeypatch, capsys, ["-o", str(target), "--to", "pdf"])
    assert code == EXIT_OK and target.read_bytes()[:5] == b"%PDF-"


def test_any_weasyprint_failure_is_a_render_error(tmp_path, monkeypatch, capsys):
    def boom(self, *a, **kw):
        raise RuntimeError("layout exploded")

    monkeypatch.setattr("weasyprint.HTML.render", boom)
    code, _, err = run(monkeypatch, capsys, ["-o", str(tmp_path / "o.pdf")])
    assert code == EXIT_RENDER and "layout exploded" in err


def test_verify_on_a_non_pdf_is_bad_input(tmp_path, capsys):
    bad = tmp_path / "notes.pdf"
    bad.write_text("not a pdf")
    code = main(["verify", str(bad)])
    _, err = capsys.readouterr()
    assert code == EXIT_INPUT and err.startswith("rupa: error: cannot read PDF")
    assert err.count("\n") == 1


def test_verify_bad_wants_value_is_bad_input(tmp_path, capsys):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    wants = tmp_path / "wants.yaml"
    wants.write_text('text_color: "#GGG"\n')
    code = main(["verify", str(pdf), "--wants", str(wants)])
    assert code == EXIT_INPUT and "text_color" in capsys.readouterr().err
