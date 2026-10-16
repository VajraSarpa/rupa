import io
import json

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


def test_remote_resources_are_blocked_in_pdf(tmp_path, monkeypatch, capsys):
    md = "## x\n\n![remote](https://example.com/a.png)\n"
    code, _, err = run(monkeypatch, capsys, ["-o", str(tmp_path / "o.pdf")], stdin=md)
    assert code == EXIT_RENDER and "example.com" in err


def test_to_flag_overrides_extension(tmp_path, monkeypatch, capsys):
    target = tmp_path / "report.out"
    code, _, _ = run(monkeypatch, capsys, ["-o", str(target), "--to", "pdf"])
    assert code == EXIT_OK and target.read_bytes()[:5] == b"%PDF-"
