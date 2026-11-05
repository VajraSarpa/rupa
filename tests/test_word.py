"""DOCX output: a valid package, the same guards as HTML and PDF, stable bytes."""

import base64
import io
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import pytest

from rupa.cli import EXIT_OK, EXIT_RENDER, EXIT_USAGE, main
from rupa.document import parse
from rupa.word import _bookmark_names, _svg_size, esc, to_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

FULL = """---
title: Word Test
subtitle: Every block
author: A. Author
date: 2026-11-05
theme: cyan
---

## Text

Plain, **bold**, *italic*, ~~gone~~, `code`, [site](https://example.com),
[jump](#tables), [file](notes.txt) and a note.[^n]

> A quote.

- One
- Two
  1. Nested

3. Three
4. Four

- [x] Done
- [ ] Todo

## Tables

| L | R |
|:--|--:|
| a | 1 |

---

```python
def f():
\treturn "<x> & y"
```

[^n]: The footnote.
"""

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20" fill="#0e7490"/></svg>'


def render(tmp_path, monkeypatch, capsys, text, *extra):
    src = tmp_path / "doc.md"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "out" / "doc.docx"
    monkeypatch.chdir(tmp_path)
    code = main([str(src), "-o", str(out), *extra])
    stdout, stderr = capsys.readouterr()
    return code, out, stdout, stderr


def parts(path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {n: z.read(n) for n in z.namelist()}


def test_writes_a_valid_package(tmp_path, monkeypatch, capsys):
    code, out, stdout, _ = render(tmp_path, monkeypatch, capsys, FULL)
    assert code == EXIT_OK
    assert stdout.count("\n") == 1 and stdout.startswith(f"rupa: wrote {out} (docx,")
    files = parts(out)
    assert next(iter(files)) == "[Content_Types].xml"
    for name, data in files.items():
        if name.endswith((".xml", ".rels")):
            ET.fromstring(data)  # every part is well-formed XML
    for required in (
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
        "word/numbering.xml",
        "word/footnotes.xml",
    ):
        assert required in files


def test_json_status(tmp_path, monkeypatch, capsys):
    code, out, stdout, _ = render(tmp_path, monkeypatch, capsys, FULL, "--json")
    status = json.loads(stdout)
    assert code == EXIT_OK and status["ok"] and status["format"] == "docx"
    assert status["pages"] is None and status["bytes"] == out.stat().st_size


def test_same_input_same_bytes():
    doc = parse(FULL, html=False)
    assert to_docx(doc, "cyan") == to_docx(parse(FULL, html=False), "cyan")
    with zipfile.ZipFile(io.BytesIO(to_docx(doc))) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_content_survives(tmp_path, monkeypatch, capsys):
    _, out, _, _ = render(tmp_path, monkeypatch, capsys, FULL)
    files = parts(out)
    body = files["word/document.xml"].decode()
    text = "".join(ET.fromstring(body).itertext())
    for phrase in ("Word Test", "Every block", "A. Author", "Plain, ", "Nested"):
        assert phrase in text
    assert 'return "<x> & y"' in text  # code kept verbatim, tab and all
    assert "<w:tab/>" in body
    assert "<w:b/>" in body and "<w:i/>" in body and "<w:strike/>" in body
    assert "☒" in text and "☐" in text  # task boxes
    assert "The footnote." in files["word/footnotes.xml"].decode()
    assert '<w:footnoteReference w:id="1"/>' in body
    # The second ordered list restarts at its own number.
    assert '<w:startOverride w:val="3"/>' in files["word/numbering.xml"].decode()
    core = files["docProps/core.xml"].decode()
    assert "rupa-theme:cyan" in core and "A. Author" in core


def test_headings_link_from_contents(tmp_path, monkeypatch, capsys):
    _, out, _, _ = render(tmp_path, monkeypatch, capsys, FULL)
    body = parts(out)["word/document.xml"].decode()
    marks = set(re.findall(r'w:bookmarkStart w:id="\d+" w:name="([^"]+)"', body))
    targets = set(re.findall(r'w:anchor="([^"]+)"', body))
    assert targets and targets <= marks  # contents and #links all resolve
    assert all(len(m) <= 40 and m.startswith("_") for m in marks)


def test_text_is_black(tmp_path, monkeypatch, capsys):
    _, out, _, _ = render(tmp_path, monkeypatch, capsys, FULL)
    files = parts(out)
    for name in ("word/document.xml", "word/styles.xml", "word/footnotes.xml"):
        colours = set(re.findall(r'<w:color w:val="([^"]+)"', files[name].decode()))
        assert colours <= {"000000"}, name


def test_only_web_links_are_links(tmp_path, monkeypatch, capsys):
    text = "# T\n\n[a](https://a.example) [m](mailto:x@y.z) [f](notes.txt) [s](ftp://h/x)\n"
    _, out, _, _ = render(tmp_path, monkeypatch, capsys, text)
    files = parts(out)
    rels = files["word/_rels/document.xml.rels"].decode()
    assert 'Target="https://a.example" TargetMode="External"' in rels
    assert 'Target="mailto:x@y.z"' in rels
    assert "notes.txt" not in rels and "ftp:" not in rels
    body = "".join(ET.fromstring(files["word/document.xml"]).itertext())
    assert "f" in body and "s" in body  # the text stays, without the link


def test_bare_urls_are_links(tmp_path, monkeypatch, capsys):
    text = "# T\n\nSee https://a.example/x, www.b.org and me@c.com. `https://code.example`\n"
    _, out, _, _ = render(tmp_path, monkeypatch, capsys, text)
    rels = parts(out)["word/_rels/document.xml.rels"].decode()
    targets = re.findall(r'Target="([^"]+)" TargetMode="External"', rels)
    assert targets == ["https://a.example/x", "http://www.b.org", "mailto:me@c.com"]


def test_raw_html_and_control_chars_are_text(tmp_path, monkeypatch, capsys):
    text = "# T\n\n<script>alert(1)</script> and a \x01bell\x0b.\n"
    code, out, _, _ = render(tmp_path, monkeypatch, capsys, text)
    assert code == EXIT_OK
    body = parts(out)["word/document.xml"]
    ET.fromstring(body)  # the control characters are gone, so it parses
    assert b"<script>" not in body and b"&lt;script&gt;" in body


def test_images_are_embedded_and_svg_is_rasterised(tmp_path, monkeypatch, capsys):
    (tmp_path / "dot.png").write_bytes(PNG)
    (tmp_path / "box.svg").write_bytes(SVG)
    text = "# T\n\n![dot](dot.png) ![again](dot.png) ![box](box.svg)\n"
    code, out, _, err = render(tmp_path, monkeypatch, capsys, text)
    assert code == EXIT_OK, err
    files = parts(out)
    media = sorted(n for n in files if n.startswith("word/media/"))
    assert media == ["word/media/image1.png", "word/media/image2.png"]  # deduped
    assert not any(n.endswith(".svg") for n in files)  # no SVG reaches Word
    assert files["word/media/image2.png"][:8] == b"\x89PNG\r\n\x1a\n"
    body = files["word/document.xml"].decode()
    assert body.count("<w:drawing>") == 3 and 'descr="dot"' in body


def test_image_outside_folder_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "doc").mkdir()
    (tmp_path / "secret.png").write_bytes(PNG)
    src = tmp_path / "doc" / "doc.md"
    src.write_text("# T\n\n![x](../secret.png)\n")
    code = main([str(src), "-o", str(tmp_path / "o.docx")])
    _, err = capsys.readouterr()
    assert code == EXIT_RENDER and "outside" in err
    assert not (tmp_path / "o.docx").exists()


def test_svg_cannot_pull_in_a_file(tmp_path, monkeypatch, capsys):
    # An SVG's own <image> must not read a file, whatever case the scheme is in.
    (tmp_path / "doc").mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(PNG)
    for href in (f"FILE://{secret}", f"file://{secret}", "../secret.png"):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
            f'<image href="{href}" width="40" height="20"/></svg>'
        )
        (tmp_path / "doc" / "pic.svg").write_text(svg)
        src = tmp_path / "doc" / "doc.md"
        src.write_text("# T\n\n![x](pic.svg)\n")
        out = tmp_path / "o.docx"
        code = main([str(src), "-o", str(out)])
        _, err = capsys.readouterr()
        assert code == EXIT_RENDER and "SVG" in err, (href, err)
        assert not out.exists()


def test_fake_image_fails(tmp_path, monkeypatch, capsys):
    (tmp_path / "env.png").write_text("SECRET=1\n")
    code, out, _, err = render(tmp_path, monkeypatch, capsys, "# T\n\n![x](env.png)\n")
    assert code == EXIT_RENDER and "cannot be decoded" in err and not out.exists()


def test_unknown_theme(tmp_path, monkeypatch, capsys):
    code, _, _, err = render(tmp_path, monkeypatch, capsys, "# T\n", "--theme", "x")
    assert code == EXIT_RENDER and "unknown theme" in err


def test_existing_docx_is_replaced_but_other_files_are_not(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"# T\n")))
    (tmp_path / "a.docx").write_bytes(b"old")
    assert main(["-o", "a.docx"]) == EXIT_OK
    assert (tmp_path / "a.docx").read_bytes()[:2] == b"PK"
    (tmp_path / "notes.txt").write_text("keep")
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"# T\n")))
    assert main(["--to", "docx", "-o", "notes.txt"]) == EXIT_USAGE
    assert (tmp_path / "notes.txt").read_text() == "keep"


def test_contents_can_be_turned_off():
    doc = parse("---\ntoc: false\n---\n\n## A\n\nx\n", html=False)
    with zipfile.ZipFile(io.BytesIO(to_docx(doc))) as z:
        assert b"ContentsHeading" not in z.read("word/document.xml")


def test_parse_without_html_keeps_tokens():
    doc = parse(FULL, html=False)
    assert doc.body_html == "" and doc.tokens
    assert doc.tokens[0].type != "front_matter"
    assert parse(FULL).tokens  # the HTML path keeps them too


def test_bookmark_names_are_word_safe():
    names = _bookmark_names(["a-b", "x" * 60, "x" * 60 + "-1", "a-b"])
    assert names["a-b"] == "_r_a_b"
    assert len(set(names.values())) == 3
    assert all(len(n) <= 40 and re.fullmatch(r"_\w+", n) for n in names.values())


def test_svg_size_follows_browsers():
    assert _svg_size(
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10"/>'
    ) == (30, 10)
    w, h = _svg_size(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="50%"/>'
    )
    assert w == 96 and h == 150
    w, h = _svg_size(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="9000" height="10"/>'
    )
    assert w == 2000  # capped before rasterising


def test_esc_drops_xml_illegal_characters():
    assert esc("a\x00b\x1fc<d>&") == "abc&lt;d&gt;&amp;"


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
def test_libreoffice_opens_it(tmp_path, monkeypatch, capsys):
    (tmp_path / "dot.png").write_bytes(PNG)
    code, out, _, _ = render(tmp_path, monkeypatch, capsys, FULL + "\n![d](dot.png)\n")
    assert code == EXIT_OK
    subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmp_path),
            str(out),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    import pdfplumber

    with pdfplumber.open(tmp_path / "doc.pdf") as pdf:
        text = "".join(page.extract_text() or "" for page in pdf.pages)
    assert "Word Test" in text and "The footnote." in text
