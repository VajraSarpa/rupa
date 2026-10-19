import base64
import io
import json

import pytest

from rupa.cli import EXIT_INPUT, EXIT_OK, EXIT_RENDER, EXIT_USAGE, main

DOC = "---\ntitle: T\n---\n\n## A\n\nBody text.\n"


def run(monkeypatch, capsys, argv, stdin=DOC):
    raw = stdin if isinstance(stdin, bytes) else stdin.encode()
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw)))
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


@pytest.mark.parametrize("theme", ["default", "cyan", "cyan-dark"])
def test_wide_image_stays_inside_the_text_column(tmp_path, theme):
    import pdfplumber
    from PIL import Image

    (tmp_path / "doc").mkdir()
    Image.new("RGB", (900, 600), "red").save(tmp_path / "doc" / "wide.png")
    md = tmp_path / "doc" / "t.md"
    md.write_text("## x\n\n![wide](wide.png)\n")
    target = tmp_path / "o.pdf"
    assert main([str(md), "-o", str(target), "--theme", theme]) == EXIT_OK
    with pdfplumber.open(target) as pdf:
        images = [(p, im) for p in pdf.pages for im in p.images]
        assert len(images) == 1
        for page, im in images:
            left, right = 0.8 * 72, page.width - 0.8 * 72  # print.css page margins
            assert im["x0"] >= left - 1 and im["x1"] <= right + 1, (im["x0"], im["x1"])
            # aspect ratio kept
            ratio = (im["x1"] - im["x0"]) / (im["bottom"] - im["top"])
            assert abs(ratio - 1.5) < 0.02


def test_html_embeds_images_so_the_file_stands_alone(tmp_path, capsys):
    target = tmp_path / "out" / "o.html"
    assert main([_image_doc(tmp_path, "fig.png"), "-o", str(target)]) == EXIT_OK
    html = target.read_text()
    assert '<img src="data:image/png;base64,' in html and "fig.png" not in html


@pytest.mark.parametrize("ext", ["pdf", "html"])
@pytest.mark.parametrize("src", ["missing.png", "../secret.png"])
def test_missing_or_outside_image_fails_the_render(tmp_path, capsys, src, ext):
    code = main([_image_doc(tmp_path, src), "-o", str(tmp_path / f"o.{ext}")])
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


def test_verify_sample_flag_overrides_wants(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "o.pdf"
    run(monkeypatch, capsys, ["-o", str(pdf)])
    code = main(["verify", str(pdf), "--sample", "flagged", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK and report["ok"] and report["sheets"] == []


LONG = "---\ntitle: T\npages: {budget}\n---\n\n" + "\n\n".join(
    f"## S{i}\n\n" + "Owning identity, detection and response in the cloud. " * 30
    for i in range(6)
)


def test_page_budget_fits_by_tightening(tmp_path, monkeypatch, capsys):
    target = tmp_path / "o.pdf"
    code, out, _ = run(
        monkeypatch, capsys, ["-o", str(target), "--json"], stdin=LONG.format(budget=3)
    )
    status = json.loads(out)
    assert code == EXIT_OK and status["ok"]
    assert status["pages"] <= 3 and status["fit"] and status["cut_lines"] == 0


def test_page_budget_over_says_how_much_to_cut(tmp_path, monkeypatch, capsys):
    target = tmp_path / "o.pdf"
    code, out, _ = run(
        monkeypatch, capsys, ["-o", str(target)], stdin=LONG.format(budget=1)
    )
    assert code == 5 and target.exists()  # the file is still written
    assert "over the 1-page budget" in out and "lines" in out


def test_pages_flag_overrides_frontmatter(tmp_path, monkeypatch, capsys):
    target = tmp_path / "o.pdf"
    code, out, _ = run(
        monkeypatch,
        capsys,
        ["-o", str(target), "--pages", "1", "--json"],
        stdin=LONG.format(budget=9),
    )
    assert code == 5 and json.loads(out)["budget"] == 1


def test_no_budget_leaves_render_alone(tmp_path, monkeypatch, capsys):
    target = tmp_path / "o.pdf"
    code, out, _ = run(monkeypatch, capsys, ["-o", str(target), "--json"])
    assert code == EXIT_OK and "fit" not in json.loads(out)


def test_cut_estimate_counts_lines_of_code():
    # A JSON block has one or two words a line, so a word count of the
    # overflow says far too little. The estimate must cover the lines.
    import io

    import pdfplumber

    from rupa.document import parse
    from rupa.render import fit_pdf

    code = "\n".join(f'  "key{i}": "value",' for i in range(150))
    fit = fit_pdf(parse(f"# T\n\n```json\n{{\n{code}\n}}\n```\n"), budget=1)
    with pdfplumber.open(io.BytesIO(fit.data)) as pdf:
        lines_past = sum(
            len((p.extract_text() or "").splitlines()) - 1 for p in pdf.pages[1:]
        )  # less the footer line
    assert lines_past <= fit.cut_lines <= lines_past * 1.3


def test_pdf_embeds_bundled_fonts():
    # Fonts ship with Rupa, so the PDF doesn't depend on what is installed.
    import io

    import pdfplumber

    from rupa.document import parse
    from rupa.render import to_pdf

    data, _ = to_pdf(parse("# T\n\nBody **bold** and `code`.\n"))
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        fonts = {c["fontname"].split("+")[-1] for c in pdf.pages[0].chars}
    assert any(f.startswith("Inter") for f in fonts)
    assert any(f.startswith("JetBrains") for f in fonts)


def _entries(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_success_is_not_logged(tmp_path, monkeypatch, capsys, _rupa_log):
    code, _, _ = run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html")])
    assert code == EXIT_OK and not _rupa_log.exists()


def test_failure_is_logged(tmp_path, monkeypatch, capsys, _rupa_log):
    argv = ["-o", str(tmp_path / "o.html")]
    code, out, err = run(monkeypatch, capsys, argv, stdin="")
    (entry,) = _entries(_rupa_log)
    assert code == EXIT_INPUT and entry["exit"] == EXIT_INPUT
    assert entry["argv"] == argv and "empty" in entry["stderr"]
    # the contract is unchanged: the user still sees the same output
    assert "empty" in err and out == ""


def test_usage_error_is_logged(tmp_path, monkeypatch, capsys, _rupa_log):
    with pytest.raises(SystemExit):
        run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html"), "--no-such-flag"])
    (entry,) = _entries(_rupa_log)
    assert entry["exit"] == EXIT_USAGE and "--no-such-flag" in entry["stderr"]


def test_crash_is_logged_with_traceback(tmp_path, monkeypatch, capsys, _rupa_log):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("rupa.cli.to_html", boom)
    with pytest.raises(RuntimeError):
        run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html")])
    (entry,) = _entries(_rupa_log)
    assert entry["exit"] == 1 and "kaboom" in entry["traceback"]


def test_log_off(tmp_path, monkeypatch, capsys, _rupa_log):
    monkeypatch.setenv("RUPA_LOG", "off")
    run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html")], stdin="")
    assert not _rupa_log.exists()


def test_to_does_not_replace_a_file_that_isnt_html_or_pdf(
    tmp_path, monkeypatch, capsys
):
    target = tmp_path / "notes.txt"
    target.write_text("keep me")
    code, _, err = run(monkeypatch, capsys, ["-o", str(target), "--to", "html"])
    assert code == EXIT_USAGE and "--force" in err
    assert target.read_text() == "keep me"
    code, _, _ = run(
        monkeypatch, capsys, ["-o", str(target), "--to", "html", "--force"]
    )
    assert code == EXIT_OK and target.read_text().startswith("<!doctype html>")


def test_existing_html_and_pdf_are_still_replaced(tmp_path, monkeypatch, capsys):
    for name in ("o.html", "o.pdf"):
        target = tmp_path / name
        target.write_text("old")
        code, _, _ = run(monkeypatch, capsys, ["-o", str(target)])
        assert code == EXIT_OK and target.read_bytes() != b"old"


def _doc_with(tmp_path, name, data, src=None):
    (tmp_path / "doc").mkdir(exist_ok=True)
    (tmp_path / "doc" / name).write_bytes(data)
    md = tmp_path / "doc" / "t.md"
    md.write_text(f"## x\n\n![f]({src or name})\n")
    return str(md)


@pytest.mark.parametrize("ext", ["pdf", "html"])
@pytest.mark.parametrize("name", [".env", "notes.txt", "fake.png", ".hidden/fig.png"])
def test_files_that_arent_real_visible_images_are_refused(tmp_path, capsys, ext, name):
    from PIL import Image

    secret = b"API_KEY=sk-not-for-the-page"
    if name.startswith(".hidden"):
        (tmp_path / "doc" / ".hidden").mkdir(parents=True)
        Image.new("RGB", (4, 4)).save(tmp_path / "doc" / name)
        md = _doc_with(tmp_path, "unused.txt", b"", src=name)
    else:
        md = _doc_with(tmp_path, name, secret)
    target = tmp_path / f"o.{ext}"
    assert main([md, "-o", str(target)]) == EXIT_RENDER
    err = capsys.readouterr().err
    assert "blocked" in err or "cannot be decoded" in err
    assert not target.exists()


@pytest.mark.parametrize("ext", ["pdf", "html"])
def test_an_image_that_wont_decode_fails_the_render(tmp_path, capsys, ext):
    from PIL import Image

    buf = io.BytesIO()
    Image.effect_noise((200, 200), 64).save(buf, "PNG")
    data = buf.getvalue()
    md = _doc_with(tmp_path, "cut.png", data[: len(data) // 2])  # truncated
    code = main([md, "-o", str(tmp_path / f"o.{ext}")])
    assert code == EXIT_RENDER and "cut.png" in capsys.readouterr().err


@pytest.mark.parametrize("ext", ["pdf", "html"])
def test_svg_images_still_render(tmp_path, capsys, ext):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="red"/></svg>'
    target = tmp_path / f"o.{ext}"
    assert main([_doc_with(tmp_path, "fig.svg", svg), "-o", str(target)]) == EXIT_OK
    if ext == "html":
        assert "data:image/svg+xml;base64," in target.read_text()


def test_non_utf8_stdin_is_bad_input_without_a_utf8_locale(
    tmp_path, monkeypatch, capsys
):
    # Under the C locale Python decodes stdin with surrogateescape, so bad
    # bytes used to slip through and crash the render (exit 1 or 4).
    stdin = io.TextIOWrapper(
        io.BytesIO(b"## caf\xe9\n"), encoding="utf-8", errors="surrogateescape"
    )
    monkeypatch.setattr("sys.stdin", stdin)
    for ext in ("html", "pdf"):
        stdin.seek(0)
        assert main(["-o", str(tmp_path / f"o.{ext}")]) == EXIT_INPUT
        assert "utf-8" in capsys.readouterr().err


@pytest.mark.parametrize(
    "stdin, needle",
    [
        ("---\ntitle: [a, b\nfoo: : :\n---\n# x\n", "bad frontmatter: line 2"),
        ("---\ntheme: " + "x" * 300 + "\n---\n# x\n", "unknown theme"),
        ("---\n" + "k" * 300 + ": 1\n---\n# x\n", "unknown frontmatter keys"),
        ("![a](http://" + "x" * 300 + ".png)\n", "must be a relative path"),
    ],
)
def test_errors_are_one_short_line(tmp_path, monkeypatch, capsys, stdin, needle):
    code, _, err = run(monkeypatch, capsys, ["-o", str(tmp_path / "o.pdf")], stdin)
    assert code != EXIT_OK and needle in err
    assert err.count("\n") == 1 and len(err) < 200


def test_bad_wants_yaml_is_one_line(tmp_path, monkeypatch, capsys):
    pdf = tmp_path / "x.pdf"
    run(monkeypatch, capsys, ["-o", str(pdf)])
    wants = tmp_path / "wants.yaml"
    wants.write_text("checks: [a, b\nfoo: : :\n")
    code = main(["verify", str(pdf), "--wants", str(wants)])
    err = capsys.readouterr().err
    assert code == EXIT_INPUT and "bad wants file: line 2" in err
    assert err.count("\n") == 1


def test_verify_missing_pdf_is_bad_input(tmp_path, capsys):
    assert main(["verify", str(tmp_path / "nope.pdf")]) == EXIT_INPUT
    assert "no such file" in capsys.readouterr().err


def test_file_named_verify_renders_with_dot_slash(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "verify").write_text(DOC)
    code = main(["./verify", "-o", "out.html"])
    capsys.readouterr()
    assert code == EXIT_OK and (tmp_path / "out.html").is_file()


@pytest.mark.parametrize("ext", ["pdf", "html"])
def test_svg_data_uri_images_render(tmp_path, ext):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="red"/></svg>'
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg).decode()
    md = tmp_path / "doc.md"
    md.write_text(f"# Logo\n\n![logo]({uri})\n")
    target = tmp_path / f"o.{ext}"
    assert main([str(md), "-o", str(target)]) == EXIT_OK
    if ext == "html":
        html = target.read_text()
        assert "<img" in html and "![logo]" not in html
    else:
        import pdfplumber

        with pdfplumber.open(target) as pdf:
            assert "![logo]" not in "".join(p.extract_text() for p in pdf.pages)


def test_refs_without_out_refuses_an_installed_copy(tmp_path, monkeypatch, capsys):
    # The default target is the package's own references/, which in an
    # installed copy would overwrite the reference pages verify compares to.
    import rupa.cli

    monkeypatch.setattr(rupa.cli, "_in_checkout", lambda pkg: False)
    code = main(["refs"])
    assert code == EXIT_USAGE and "--out" in capsys.readouterr().err


def test_in_checkout_tells_src_from_site_packages(tmp_path):
    from rupa.cli import _in_checkout

    (tmp_path / "pyproject.toml").write_text("")
    assert _in_checkout(tmp_path / "src" / "rupa")
    assert not _in_checkout(tmp_path / "lib" / "site-packages" / "rupa")


def test_refs_to_a_file_is_one_line_bad_input(tmp_path, capsys):
    blocker = tmp_path / "refs"
    blocker.write_text("x")
    assert main(["refs", "--out", str(blocker)]) == EXIT_INPUT
    assert "cannot write to" in capsys.readouterr().err


def test_log_is_private_and_clipped(tmp_path, monkeypatch, capsys, _rupa_log):
    import stat

    _rupa_log.write_text("")
    _rupa_log.chmod(0o644)  # as an older rupa left it
    long = "x" * 50_000
    run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html"), long], stdin="")
    (entry,) = _entries(_rupa_log)
    assert stat.S_IMODE(_rupa_log.stat().st_mode) == 0o600
    assert len(json.dumps(entry)) < 10_000


def test_log_rotates_past_its_cap(tmp_path, monkeypatch, capsys, _rupa_log):
    import rupa.cli

    monkeypatch.setattr(rupa.cli, "LOG_MAX_BYTES", 100)
    _rupa_log.write_text("old\n" * 50)
    run(monkeypatch, capsys, ["-o", str(tmp_path / "o.html")], stdin="")
    assert len(_entries(_rupa_log)) == 1
    assert (_rupa_log.parent / (_rupa_log.name + ".1")).read_text() == "old\n" * 50


def test_bench_summary_skips_malformed_results(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "summarize", Path(__file__).parent.parent / "bench" / "summarize.py"
    )
    summarize = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(summarize)
    (tmp_path / "rupa-1.json").write_text("[1, 2]")
    (tmp_path / "rupa-2.json").write_text('{"usage": null, "num_turns": null}')
    (tmp_path / "rupa-3.json").write_text('{"num_turns": 6, "total_cost_usd": 0.3}')
    summarize.main(tmp_path)  # used to raise AttributeError
    rows = capsys.readouterr().out.split("\n\n")[0].splitlines()[1:]
    assert [r.split("\t")[2] for r in rows] == ["0", "6"]
