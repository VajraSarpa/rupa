"""Property and fuzz tests for the CLI contract, the image guard and verify.

The default run is capped (RUPA_FUZZ_EXAMPLES, default 15 examples per
property) so the suite stays fast. For a deep run:

    RUPA_FUZZ_EXAMPLES=1000 uv run pytest tests/test_fuzz.py -q

Every bug these found is pinned as a test_bugNN_* test at the bottom;
docs/fuzz-2026-10.md explains each one and the fix. A new bug goes there
as xfail(strict=True) until it's fixed.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import io
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber
import pytest
import yaml
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from PIL import Image

from rupa.cli import main
from rupa.document import ALLOWED_META, InputError, parse
from rupa.render import to_html
from rupa.verify import ALL_CHECKS, DEFAULT_WANTS, SAMPLE_MODES

pytestmark = pytest.mark.fuzz

settings.register_profile(
    "rupa-fuzz",
    max_examples=int(os.environ.get("RUPA_FUZZ_EXAMPLES", "15")),
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.load_profile("rupa-fuzz")
# PDF renders cost about half a second each; those properties take a share.
PDF_EXAMPLES = max(3, settings.default.max_examples // 3)

CONTRACT_CODES = {0, 2, 3, 4, 5}
CRASH = 1


# ---------------------------------------------------------------- harness


def run_cli(argv: list[str], stdin: bytes = b"") -> tuple[int, str, str]:
    """Run rupa in-process: (exit code, stdout, stderr). A crash is code 1."""
    old = sys.stdin, sys.stdout, sys.stderr
    out, err = io.StringIO(), io.StringIO()
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin))
    sys.stdout, sys.stderr = out, err
    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception:  # noqa: BLE001 - a crash is what we are looking for
        code = CRASH
    finally:
        sys.stdin, sys.stdout, sys.stderr = old
    return code, out.getvalue(), err.getvalue()


def assert_contract(code: int, out: str, err: str, json_mode: bool = False) -> None:
    """Exit codes 0/2/3/4/5; one stdout line on success; one stderr line on error."""
    assert code in CONTRACT_CODES, f"exit {code}\nstdout={out!r}\nstderr={err[-800:]}"
    if json_mode and code != 2:  # argparse usage errors don't speak JSON (bug 12)
        assert out.count("\n") == 1, out
        json.loads(out)
        assert err == ""
        return
    if code in (0, 5) and out:  # verify prints its line on both
        assert out.count("\n") == 1, out
        assert err == "", err
    elif code in (3, 4) or (code == 5 and not out):
        assert out == ""
        assert err.count("\n") == 1 and err.startswith("rupa: error: "), err


@pytest.fixture
def no_network(monkeypatch):
    """Record, and refuse, every attempt to reach the network."""
    attempts: list = []

    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("network disabled by test_fuzz")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    opened: list = []
    real_open = urllib.request.OpenerDirector.open

    def spy(self, req, *args, **kwargs):
        url = getattr(req, "full_url", req)
        opened.append(url)
        return real_open(self, req, *args, **kwargs)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", spy)
    return attempts, opened


# ---------------------------------------------------------------- strategies

# fmt: off
MD_FRAGMENTS = [
    "# ", "## ", "### ", "#### ", "\n", "\n\n", "    ", "> ", "- ", "1. ", "* ",
    "- [ ] ", "- [x] ", "**", "*", "_", "~~", "`", "```", "```python\n",
    "```nosuchlang\n", "~~~\n", "| a | b |\n|---|:-:|\n| 1 | 2 |\n", "---\n", "***\n",
    "[^1]", "[^1]: note\n", "^[inline note]", "[link](x.md)",
    "[link](http://example.com)", "<http://example.com>", "[ref]\n\n[ref]: /x\n",
    "![alt](missing.png)", "![a](data:image/png;base64,AAAA)", "&amp;", "&#x0;",
    "&#xD800;", "&nbsp;", "<script>alert(1)</script>", "<!-- c -->", "\\", "\t",
    "\r\n", "\x00", "\u202e", "\u0301", "🙂", "a" * 200, "\\\n", "<", ">", "[", "]",
    "(", ")", "!", "{{ title }}", "{% raw %}",
]
# fmt: on
markdown = st.lists(
    st.one_of(st.sampled_from(MD_FRAGMENTS), st.text(max_size=30)), max_size=40
).map("".join)

yaml_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=40),
    st.dates(min_value=date(1, 1, 1)),
    st.sampled_from(THEME_NAMES := ["default", "cyan", "cyan-dark", "nope", ""]),
)
yaml_values = st.recursive(
    yaml_scalars,
    lambda kids: (
        st.lists(kids, max_size=3)
        | st.dictionaries(st.text(max_size=8), kids, max_size=3)
    ),
    max_leaves=8,
)
meta_keys = st.one_of(st.sampled_from(sorted(ALLOWED_META)), st.text(max_size=10))


@st.composite
def frontmatter(draw) -> str:
    kind = draw(st.sampled_from(["none", "dump", "raw"]))
    if kind == "none":
        return ""
    if kind == "dump":
        meta = draw(st.dictionaries(meta_keys, yaml_values, max_size=6))
        body = yaml.safe_dump(meta, allow_unicode=draw(st.booleans()))
    else:
        # fmt: off
        raw_bits = [
            "title: ", "theme: ", "toc: ", "pages: ", "date: ", "&a ", "*a", "<<: ",
            "!!binary ", "!!python/object:os.system ", "[", "]", "{", "}", ": ", "- ",
            "\n", "  ", "'", '"', "2026-02-30", "0x1F", "~",
        ]
        # fmt: on
        body = draw(
            st.lists(
                st.one_of(st.sampled_from(raw_bits), st.text(max_size=12)),
                max_size=20,
            ).map("".join)
        )
    return f"---\n{body}\n---\n"


documents = st.tuples(frontmatter(), markdown).map("".join)


# ---------------------------------------------------------------- CLI contract


@given(doc=documents, json_mode=st.booleans())
def test_cli_never_crashes_on_markdown_and_frontmatter_html(
    tmp_path, no_network, doc, json_mode
):
    out = tmp_path / "o.html"
    argv = ["-o", str(out)] + (["--json"] if json_mode else [])
    code, stdout, stderr = run_cli(argv, doc.encode("utf-8"))
    assert_contract(code, stdout, stderr, json_mode)
    assert no_network[0] == []


@settings(max_examples=PDF_EXAMPLES)
@given(doc=documents, pages=st.sampled_from([None, 1, 2]))
def test_cli_never_crashes_on_markdown_and_frontmatter_pdf(
    tmp_path, no_network, doc, pages
):
    out = tmp_path / "o.pdf"
    argv = ["-o", str(out)] + (["--pages", str(pages)] if pages else [])
    code, stdout, stderr = run_cli(argv, doc.encode("utf-8"))
    assert_contract(code, stdout, stderr)
    assert no_network[0] == []
    if code in (0, 5):
        assert out.read_bytes().startswith(b"%PDF")


@given(raw=st.binary(max_size=300))
def test_cli_never_crashes_on_arbitrary_bytes(tmp_path, raw):
    code, stdout, stderr = run_cli(["-o", str(tmp_path / "o.html")], raw)
    assert_contract(code, stdout, stderr)


# fmt: off
_ARG_BITS = [
    "-o", "--output", "--to", "html", "pdf", "--theme", "cyan", "nope", "--pages", "0",
    "-1", "3", "x", "--force", "--json", "--wants", "--sample", "--out", "verify",
    "refs", "-", "--", "-h", "--version", "--forc", "a.txt",
]
# fmt: on


@given(
    argv=st.lists(
        st.one_of(st.sampled_from(_ARG_BITS), st.text(max_size=6)), max_size=7
    )
)
def test_cli_arguments_never_crash(tmp_path, monkeypatch, argv):
    # Every path lands in tmp_path; refs is a maintainer command that rebuilds
    # PNGs, so keep it away from the real reference pages.
    assume("refs" not in argv)
    assume(not any("\x00" in a for a in argv))  # no real argv can hold a NUL
    monkeypatch.chdir(tmp_path)
    code, stdout, stderr = run_cli(argv, b"# Hi\n")
    assert code in CONTRACT_CODES, (argv, stderr[-600:])
    if "-h" in argv or "--help" in argv:
        return  # help text is meant to span lines
    assert stdout.count("\n") <= 1 or argv[:1] == ["verify"] and "--json" in argv


# ---------------------------------------------------------------- escaping

# fmt: off
BODY_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "em", "strong", "code", "pre",
    "span", "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th",
    "td", "s", "hr", "br", "input", "sup", "section", "label",
}
# fmt: on
# fmt: off
PAGE_TAGS = BODY_TAGS | {
    "html", "head", "meta", "title", "style", "body", "header", "nav", "main",
}
# fmt: on
# fmt: off
SAFE_ATTRS = {
    "href", "src", "alt", "title", "id", "class", "style", "type", "checked",
    "disabled", "start", "name", "content", "charset", "lang", "for",
}
# fmt: on


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, list]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs))

    handle_startendtag = handle_starttag


def live_tags(html: str) -> list[tuple[str, list]]:
    parser = _Tags()
    parser.feed(html)
    parser.close()
    return parser.tags


# fmt: off
HTML_BITS = [
    "<script>alert(1)</script>", "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">x</a>', "<iframe src=//e.com>", "<svg/onload=x>",
    "<style>*{}</style>", "<!--", "-->", "<![CDATA[", "]]>", "<?php ?>", "</p>",
    "<div>", "<b onclick=x>", "<", ">", '"', "'", "&lt;", "&#60;", "&#x3c;", "=",
    "javascript:", "[x](javascript:alert(1))", "[x](JaVaScRiPt:alert(1))",
    "[x](data:text/html,<script>)", "![x](javascript:a)", '[x](y "<b>t</b>")',
    "<javascript:alert(1)>", "`<code>`", "```<lang>\n<pre>\n```\n",
    "| <b> | c |\n|---|---|\n| <i> | d |\n", "# <h1>head</h1>\n", "[^<x>]: <y>\n",
    "- [ ] <input>\n", "\n", " ",
]
# fmt: on
html_markdown = st.lists(
    st.one_of(st.sampled_from(HTML_BITS), st.sampled_from(MD_FRAGMENTS)), max_size=25
).map("".join)
meta_text = st.lists(st.sampled_from(HTML_BITS), max_size=4).map("".join)


@given(text=html_markdown, title=meta_text, subtitle=meta_text, author=meta_text)
def test_raw_html_never_comes_out_live(text, title, subtitle, author):
    meta = {"title": title, "subtitle": subtitle, "author": author, "toc": True}
    source = "---\n" + yaml.safe_dump(meta) + "---\n" + text
    try:
        doc = parse(source)
    except InputError:
        return
    for tag, attrs in live_tags(doc.body_html):
        assert tag in BODY_TAGS, (tag, source)
        for name, value in attrs:
            assert name in SAFE_ATTRS and not name.startswith("on"), (name, source)
            if name in ("href", "src") and value:
                scheme = value.strip().lower()
                assert not scheme.startswith(("javascript:", "vbscript:")), source
                assert not scheme.startswith("data:") or scheme.startswith(
                    "data:image/"
                ), source
    page = to_html(doc)
    tags = live_tags(page)
    assert {t for t, _ in tags} <= PAGE_TAGS
    assert [t for t, _ in tags].count("style") == 1  # the theme's own
    assert all(not n.startswith("on") for _, attrs in tags for n, _ in attrs)


# ---------------------------------------------------------------- containment

# Each planted image has a size no other image has, so a PDF's or an HTML
# page's embedded images say exactly which files were read.
ALLOWED = (11, 7)
HIDDEN, OUTSIDE, WRONG_EXT = (13, 7), (17, 7), (19, 7)
FORBIDDEN = {HIDDEN, OUTSIDE, WRONG_EXT}


@pytest.fixture(scope="module")
def sandbox():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        doc = root / "doc"
        (doc / ".h").mkdir(parents=True)
        (doc / "sub").mkdir()
        Image.new("RGB", ALLOWED, "green").save(doc / "ok.png")
        Image.new("RGB", ALLOWED, "green").save(doc / "sub" / "ok.png")
        Image.new("RGB", HIDDEN, "blue").save(doc / ".h" / "in.png")
        Image.new("RGB", HIDDEN, "blue").save(doc / ".hid.png")
        Image.new("RGB", OUTSIDE, "red").save(root / "out.png")
        Image.new("RGB", WRONG_EXT, "gray").save(doc / "secret.dat", format="PNG")
        (doc / "link.png").symlink_to(root / "out.png")
        (doc / "dirlink").symlink_to(root)
        yield root


def _src_paths(root: Path) -> st.SearchStrategy[str]:
    doc = root / "doc"
    # fmt: off
    segment = st.sampled_from(
        [
            "..", ".", "ok.png", "sub", ".h", "in.png", ".hid.png", "out.png",
            "link.png", "dirlink", "secret.dat", "%2e%2e", "%2E%2e%2Fout.png", "doc",
            "", "%2f", "\\..\\out.png", "ok.png%23", "ok.png?x=1",
        ]
    )
    # fmt: on
    # fmt: off
    prefix = st.sampled_from(
        [
            "", "./", "/", "//", "file:", "file://", "file:///", "FILE://", "File:",
            f"{doc}/", f"{root}/", f"file://{doc}/", "http://127.0.0.1:9/",
            "https://example.com/", "//127.0.0.1/", "ftp://127.0.0.1/",
            "\\\\127.0.0.1\\", "c:\\", "data:,", "DATA:image/png,",
        ]
    )
    # fmt: on
    return st.tuples(prefix, st.lists(segment, min_size=1, max_size=4)).map(
        lambda t: t[0] + "/".join(t[1])
    )


def _svg_uri(href: str) -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink='
        '"http://www.w3.org/1999/xlink" width="40" height="40">'
        f'<image href="{href}" width="20" height="20"/>'
        f'<image xlink:href="{href}" width="20" height="20"/></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _embedded_sizes_pdf(data: bytes) -> set[tuple[int, int]]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return {
            tuple(int(v) for v in im["srcsize"]) for p in pdf.pages for im in p.images
        }


def _embedded_sizes_html(html: str) -> set[tuple[int, int]]:
    sizes = set()
    for uri in re.findall(r'<img src="(data:image/[^;"]+;base64,[^"]+)"', html):
        if uri.startswith("data:image/svg"):
            continue
        payload = base64.b64decode(uri.split(",", 1)[1])
        with Image.open(io.BytesIO(payload)) as img:
            sizes.add(img.size)
    return sizes


def _containment(sandbox, no_network, src, fmt, svg):
    root = sandbox
    if svg:
        src = _svg_uri(src)
    md = root / "doc" / "in.md"
    md.write_text(f"# T\n\n![x]({src})\n\n[link]({src})\n", encoding="utf-8")
    out = root / f"o.{fmt}"
    out.unlink(missing_ok=True)
    code, stdout, stderr = run_cli([str(md), "-o", str(out)])
    assert_contract(code, stdout, stderr)
    attempts, opened = no_network
    assert attempts == [], (src, attempts)
    assert all(
        u.split(":", 1)[0].lower() in ("file", "data") for u in map(str, opened)
    ), (src, opened)
    if code == 0:
        sizes = (
            _embedded_sizes_pdf(out.read_bytes())
            if fmt == "pdf"
            else _embedded_sizes_html(out.read_text(encoding="utf-8"))
        )
        assert not sizes & FORBIDDEN, (src, sizes)
        if fmt == "html":
            assert "http" not in out.read_text(encoding="utf-8").split("<main>")[1]


@pytest.mark.parametrize("svg", [False, True], ids=["direct", "inside-svg"])
@given(data=st.data())
def test_no_image_escapes_the_folder_html(sandbox, no_network, svg, data):
    src = data.draw(_src_paths(sandbox))
    _containment(sandbox, no_network, src, "html", svg)


@pytest.mark.parametrize("svg", [False, True], ids=["direct", "inside-svg"])
@settings(max_examples=PDF_EXAMPLES)
@given(data=st.data())
def test_no_image_escapes_the_folder_pdf(sandbox, no_network, svg, data):
    src = data.draw(_src_paths(sandbox))
    _containment(sandbox, no_network, src, "pdf", svg)


# ---------------------------------------------------------------- verify on bad PDFs


def build_pdf(objs: list[bytes], trailer: str = "") -> bytes:
    """A PDF with a correct xref table from numbered object bodies (1-based)."""
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R {trailer}>>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


def _stream(content: bytes, extra: str = "") -> bytes:
    return (
        b"<< /Length %d %s >>\nstream\n"
        % (
            len(content),
            extra.encode(),
        )
        + content
        + b"\nendstream"
    )


HELLO = b"BT /F1 12 Tf 72 700 Td (Hello) Tj ET"
FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def page_pdf(
    mediabox: str = "0 0 612 792", contents: list[bytes] | None = None, extra=b""
) -> bytes:
    contents = [HELLO] if contents is None else contents
    n = len(contents)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    font = 3 + 2 * n
    for i, content in enumerate(contents):
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [{mediabox}] "
            f"/Contents {4 + 2 * i} 0 R /Resources << /Font << /F1 {font} 0 R >> "
            f"{extra.decode()} >> >>".encode()
        )
        objs.append(_stream(content))
    objs.append(FONT)
    return build_pdf(objs)


_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    s, j = list(range(256)), 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def encrypted_pdf(user_password: bytes = b"") -> bytes:
    """One page, RC4 40-bit (Standard handler, R2), owner password 'owner'."""

    def pad(p: bytes) -> bytes:
        return (p + _PAD)[:32]

    owner = _rc4(hashlib.md5(pad(b"owner")).digest()[:5], pad(user_password))
    perms, doc_id = -4, b"0123456789abcdef"
    key = hashlib.md5(
        pad(user_password) + owner + struct.pack("<i", perms) + doc_id
    ).digest()[:5]
    user = _rc4(key, _PAD)
    obj_key = hashlib.md5(key + struct.pack("<I", 4)[:3] + b"\0\0").digest()[:10]
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        _stream(_rc4(obj_key, HELLO)),
        FONT,
        b"<< /Filter /Standard /V 1 /R 2 /O <%s> /U <%s> /P -4 >>"
        % (owner.hex().encode(), user.hex().encode()),
    ]
    return build_pdf(objs, f"/Encrypt 6 0 R /ID [<{doc_id.hex()}> <{doc_id.hex()}>] ")


def pattern_pdf() -> bytes:
    """Valid PDF whose text is filled with a tiling pattern, not a colour."""
    tile = b"0 0 1 rg 0 0 4 4 re f"
    pattern = _stream(
        tile,
        "/PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 8 8] /XStep 8"
        " /YStep 8 /Resources << >>",
    )
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
            b" /Resources << /Font << /F1 5 0 R >> /Pattern << /P0 6 0 R >> >> >>"
        ),
        _stream(b"/Pattern cs /P0 scn BT /F1 24 Tf 72 700 Td (Hello) Tj ET"),
        FONT,
        pattern,
    ]
    return build_pdf(objs)


@functools.cache
def _rupa_pdf() -> bytes:
    """A real Rupa PDF (two pages, a table, code) to mutate."""
    from rupa.render import to_pdf

    md = (
        "---\ntitle: Fuzz\n---\n\n## One\n\nText. " * 3
        + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nx = 1\n```\n"
    )
    data, _ = to_pdf(parse(md))
    return data


class _PdfBytes(bytes):
    """Prints as a name, so hypothesis's failure report stays short."""

    def __repr__(self):
        return f"<rupa pdf, {len(self)} bytes>"


@pytest.fixture
def rupa_pdf():
    return _PdfBytes(_rupa_pdf())


def _verify(tmp_path: Path, data: bytes, *extra: str) -> tuple[int, str, str]:
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(data)
    return run_cli(["verify", str(pdf), "--out", str(tmp_path / "v"), *extra])


def assert_verify_contract(code: int, out: str, err: str) -> None:
    assert code in (0, 3, 5), f"exit {code}\n{err[-800:]}"
    if code == 3:
        assert out == "" and err.count("\n") == 1, err
        assert err.startswith("rupa: error: ")
    else:
        assert out.count("\n") == 1 and out.startswith("verify: "), out
        assert err == "", err


@settings(max_examples=PDF_EXAMPLES)
@given(data=st.data())
def test_verify_never_crashes_on_mutated_pdfs(tmp_path, rupa_pdf, data):
    pdf = bytearray(rupa_pdf)
    for _ in range(data.draw(st.integers(0, 4))):
        op = data.draw(st.sampled_from(["truncate", "flip", "splice", "delete"]))
        at = data.draw(st.integers(0, max(0, len(pdf) - 1)))
        if op == "truncate":
            del pdf[at:]
        elif op == "flip" and pdf:
            pdf[at] ^= data.draw(st.integers(1, 255))
        elif op == "splice":
            pdf[at:at] = data.draw(st.binary(max_size=64))
        elif op == "delete":
            del pdf[at : at + data.draw(st.integers(1, 2000))]
    assert_verify_contract(*_verify(tmp_path, bytes(pdf)))


_number = st.one_of(
    st.integers(-(10**6), 10**6).map(str),
    st.floats(allow_nan=False, allow_infinity=False, width=32).map(
        lambda f: f"{f:.3f}"
    ),
    st.sampled_from(["0", "-0", "14400", "1e9", "nan", "/Name", "()", "[]", "null"]),
)
# fmt: off
_ops = st.sampled_from(
    [
        HELLO, b"BT /F1 300 Tf -500 700 Td (Wide) Tj ET", b"BT /F2 12 Tf (x) Tj ET",
        b"BT (no font) Tj ET", b"q 1e30 0 0 1e30 0 0 cm Q", b"1 0 0 rg", b"0.5 g",
        b"0 0 0 1 k", b"0 0 100 100 re f", b"BT /F1 12 Tf 0 0 Td <00ff> Tj ET",
        b"(unbalanced", b"BT /F1 0 Tf (zero) Tj ET", b"", b"ET ET BT",
        b"/DeviceN cs 1 scn", b"BT /F1 12 Tf 72 30 Td (footer) Tj ET",
    ]
)
# fmt: on


@settings(max_examples=PDF_EXAMPLES)
@given(
    box=st.lists(_number, min_size=4, max_size=4).map(" ".join),
    pages=st.lists(st.lists(_ops, max_size=4).map(b"\n".join), max_size=4),
    sample=st.sampled_from(SAMPLE_MODES),
)
def test_verify_never_crashes_on_odd_pages(tmp_path, box, pages, sample):
    code, out, err = _verify(tmp_path, page_pdf(box, pages), "--sample", sample)
    assert_verify_contract(code, out, err)


wants_values = st.one_of(
    yaml_values,
    st.sampled_from(sorted(SAMPLE_MODES) + THEME_NAMES + ["letter", "a4", "#000000"]),
    st.lists(st.sampled_from(list(ALL_CHECKS) + ["nope"]), max_size=4),
    st.integers(-5, 400),
    st.floats(-1, 2),
)
wants_files = st.fixed_dictionaries(
    {},
    optional={
        **{k: wants_values for k in DEFAULT_WANTS if k != "vision"},
        "vision": st.one_of(
            yaml_values,
            st.fixed_dictionaries(
                {}, optional={k: wants_values for k in DEFAULT_WANTS["vision"]}
            ),
        ),
        "extra": wants_values,
    },
).map(yaml.safe_dump)


@settings(max_examples=PDF_EXAMPLES)
@given(
    wants=st.one_of(wants_files, st.text(max_size=80)),
    json_mode=st.booleans(),
)
def test_verify_never_crashes_on_wants_files(tmp_path, rupa_pdf, wants, json_mode):
    path = tmp_path / "wants.yaml"
    path.write_text(wants, encoding="utf-8")
    argv = ["--wants", str(path)] + (["--json"] if json_mode else [])
    code, out, err = _verify(tmp_path, rupa_pdf, *argv)
    assert code in (0, 3, 5), err[-800:]
    if json_mode:  # errors are a JSON object on stdout too
        # verify's JSON is the indented verify.json; an error is one line.
        assert code != 3 or out.count("\n") == 1
        status = json.loads(out)
        assert status["pages"] == 2 if code != 3 else status["ok"] is False
    elif code == 3:
        assert err.count("\n") == 1 and out == ""
    else:
        assert out.count("\n") == 1


# Robustness that held: these are plain regression tests, not bugs.


@pytest.mark.parametrize(
    "name, data",
    [
        ("empty", b""),
        ("not a pdf", b"hello"),
        ("header only", b"%PDF-1.4\n"),
        (
            "zero pages",
            build_pdf(
                [
                    b"<< /Type /Catalog /Pages 2 0 R >>",
                    b"<< /Type /Pages /Kids [] /Count 0 >>",
                ]
            ),
        ),
        ("zero-size page", page_pdf("0 0 0 0")),
        ("password", encrypted_pdf(b"secret")),
    ],
)
def test_verify_refuses_unreadable_pdfs_as_bad_input(tmp_path, name, data):
    code, out, err = _verify(tmp_path, data)
    assert code == 3 and out == "" and err.count("\n") == 1, (name, err)


def test_verify_truncated_rupa_pdf_is_bad_input_at_every_cut(tmp_path, rupa_pdf):
    for cut in range(0, len(rupa_pdf), max(1, len(rupa_pdf) // 25)):
        code, _out, err = _verify(tmp_path, rupa_pdf[:cut])
        assert code in (0, 3, 5) and err.count("\n") <= 1, (cut, err)


def test_verify_reads_an_encrypted_pdf_with_no_user_password(tmp_path):
    code, out, _ = _verify(tmp_path, encrypted_pdf())
    assert code == 0 and out.startswith("verify: 9/9")


@pytest.mark.parametrize("box", ["0 0 14400 14400", "0 0 14400 10", "0 0 -612 -792"])
def test_verify_huge_or_inverted_page_caps_the_sheet(tmp_path, box):
    code, _out, err = _verify(tmp_path, page_pdf(box))
    assert code in (0, 5), err
    for sheet in (tmp_path / "v").glob("sheet-*.png"):
        with Image.open(sheet) as img:
            assert max(img.size) <= 2 * 3300 + 64


def test_frontmatter_alias_bomb_is_bad_input(tmp_path):
    bomb = "---\na: &a [x, x]\nb: &b [*a, *a]\nc: [*b, *b]\n---\n# x\n"
    code, _, err = run_cli(["-o", str(tmp_path / "o.html")], bomb.encode())
    assert code == 3 and "aliases" in err


def test_deeply_nested_frontmatter_is_bad_input(tmp_path):
    deep = "---\ntitle: " + "[" * 3000 + "]" * 3000 + "\n---\n# x\n"
    code, _, err = run_cli(["-o", str(tmp_path / "o.html")], deep.encode())
    assert code == 3 and err.count("\n") == 1


# ---------------------------------------------------------------- bugs found
#
# Each test states the contract; it fails today. Numbers match
# docs/fuzz-2026-10.md.

HEX = "0x" + "F" * 4000  # a valid YAML int with more than 4300 decimal digits


def _xfail(n: int, reason: str):
    return pytest.mark.xfail(strict=True, reason=f"bug {n}: {reason}")


@pytest.mark.parametrize(
    "line, want",
    [
        (f"title: {HEX}", 0),
        (f"date: {HEX}", 0),
        (f"theme: {HEX}", 3),
        (f"toc: {HEX}", 3),
    ],
)
def test_bug01_huge_frontmatter_int_crashes(tmp_path, line, want):
    code, _out, err = run_cli(
        ["-o", str(tmp_path / "o.html")], f"---\n{line}\n---\n# x\n".encode()
    )
    assert code == want, err[-300:]


def test_bug01_huge_pages_budget_crashes_json_status(tmp_path):
    doc = f"---\npages: {HEX}\n---\n# x\n".encode()
    code, out, err = run_cli(["-o", str(tmp_path / "o.pdf"), "--json"], doc)
    assert code == 0 and json.loads(out)["ok"], err[-300:]


def test_bug02_surrogate_in_frontmatter_crashes_html(tmp_path):
    doc = b'---\ntitle: "\\uD800"\n---\n# x\n'
    code, _out, err = run_cli(["-o", str(tmp_path / "o.html")], doc)
    assert code == 3 and err.count("\n") == 1, err[-300:]


@pytest.mark.parametrize("ext", ["html", "pdf"])
def test_bug03_nul_in_image_path_crashes(tmp_path, ext):
    code, _out, err = run_cli(
        ["-o", str(tmp_path / f"o.{ext}")], b"# x\n\n![x](a%00.png)\n"
    )
    assert code in (3, 4) and err.count("\n") == 1, err[-300:]


def test_bug04_svg_image_with_uppercase_file_url_escapes_the_folder(sandbox):
    out_png = sandbox / "out.png"
    md = sandbox / "doc" / "bug4.md"
    md.write_text(f"# T\n\n![x]({_svg_uri(f'FILE://{out_png}')})\n")
    pdf = sandbox / "bug4.pdf"
    code, _, _ = run_cli([str(md), "-o", str(pdf)])
    assert code == 4 or OUTSIDE not in _embedded_sizes_pdf(pdf.read_bytes())


@pytest.mark.parametrize(
    "rel, size", [(".h/in.png", HIDDEN), ("secret.dat", WRONG_EXT)]
)
def test_bug05_svg_image_reads_hidden_or_non_image_files(sandbox, rel, size):
    md = sandbox / "doc" / "bug5.md"
    md.write_text(f"# T\n\n![x]({_svg_uri(f'file://{sandbox}/doc/{rel}')})\n")
    pdf = sandbox / "bug5.pdf"
    code, _, _ = run_cli([str(md), "-o", str(pdf)])
    assert code == 4 or size not in _embedded_sizes_pdf(pdf.read_bytes())


def _wants_run(tmp_path, rupa_pdf, body: bytes):
    path = tmp_path / "wants.yaml"
    path.write_bytes(body)
    return _verify(tmp_path, rupa_pdf, "--wants", str(path))


def test_bug06_non_utf8_wants_crashes(tmp_path, rupa_pdf):
    code, _, err = _wants_run(
        tmp_path, rupa_pdf, "theme: d\xe9fault\n".encode("latin-1")
    )
    assert code == 3 and err.count("\n") == 1, err[-300:]


def test_bug07_deeply_nested_wants_crashes(tmp_path, rupa_pdf):
    code, _, err = _wants_run(
        tmp_path, rupa_pdf, b"rubric: " + b"[" * 5000 + b"]" * 5000
    )
    assert code == 3 and err.count("\n") == 1, err[-300:]


def test_bug08_impossible_date_in_wants_crashes(tmp_path, rupa_pdf):
    code, _, err = _wants_run(tmp_path, rupa_pdf, b"theme: 2026-02-30\n")
    assert code == 3 and err.count("\n") == 1, err[-300:]


@pytest.mark.parametrize(
    "line, want", [(f"max_pages: {HEX}", 0), (f"text_color: {HEX}", 3)]
)
def test_bug09_huge_int_in_wants_crashes(tmp_path, rupa_pdf, line, want):
    code, _, err = _wants_run(tmp_path, rupa_pdf, line.encode())
    assert code == want, err[-300:]


@pytest.mark.parametrize(
    "line", ["text_color: '" + "x" * 500 + "'", "checks: ['" + "x" * 500 + "']"]
)
def test_bug10_wants_errors_quote_values_unclipped(tmp_path, rupa_pdf, line):
    code, _, err = _wants_run(tmp_path, rupa_pdf, line.encode())
    assert code == 3 and len(err) < 200, len(err)


def test_bug11_newline_in_output_path_splits_status_line(tmp_path):
    code, out, _ = run_cli(["-o", str(tmp_path / "a\nb.html")], b"# x\n")
    assert code == 0 and out.count("\n") == 1, out


def test_bug11_newline_in_pdf_path_splits_verify_line(tmp_path, rupa_pdf):
    pdf = tmp_path / "a\nb.pdf"
    pdf.write_bytes(rupa_pdf)
    code, out, _ = run_cli(["verify", str(pdf), "--sample", "all"])
    assert code in (0, 5) and out.count("\n") == 1, out


@pytest.mark.parametrize(
    "argv",
    [[], ["-o", "x.pdf", "--pages", "abc"], ["verify"], ["-o", "x.pdf", "--nope"]],
)
def test_bug12_usage_errors_are_one_line(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    code, _, err = run_cli(argv, b"# x\n")
    assert code == 2 and err.count("\n") == 1, err


def test_bug12_usage_error_with_json_prints_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = run_cli(["-o", "x.pdf", "--pages", "abc", "--json"], b"# x\n")
    assert code == 2 and json.loads(out)["ok"] is False


def test_bug13_pdfminer_warnings_add_stderr_lines(tmp_path):
    # Run as a subprocess: pytest's own log handler would swallow the warning.
    pdf = tmp_path / "box.pdf"
    pdf.write_bytes(page_pdf("0 0 1e9 1e9"))
    proc = subprocess.run(
        [sys.executable, "-m", "rupa.cli", "verify", str(pdf)],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RUPA_LOG": "off"},
    )
    assert proc.returncode in (0, 3, 5)
    assert proc.stderr.count("\n") <= 1, proc.stderr


def test_bug14_pattern_filled_text_is_not_an_unreadable_pdf(tmp_path):
    code, _out, err = _verify(tmp_path, pattern_pdf())
    assert code in (0, 5), err  # a text-color failure, not 'cannot read PDF'


def test_bug15_password_pdf_error_says_why(tmp_path):
    code, _, err = _verify(tmp_path, encrypted_pdf(b"secret"))
    reason = err.split("in.pdf", 1)[1]  # the tmp path names this test
    assert code == 3 and "password" in reason.lower(), err


@pytest.mark.parametrize("prefix", ["DATA:image/png;base64,", "data:image/png;BASE64,"])
def test_bug16_uppercase_data_uri_is_refused(tmp_path, prefix):
    buf = io.BytesIO()
    Image.new("RGB", (5, 5)).save(buf, format="PNG")
    src = prefix + base64.b64encode(buf.getvalue()).decode()
    code, _, err = run_cli(["-o", str(tmp_path / "o.html")], f"![x]({src})\n".encode())
    assert code == 0, err


def test_bug17_bom_hides_frontmatter(tmp_path):
    out = tmp_path / "o.html"
    doc = "\ufeff---\ntitle: Bom Title\n---\n\nBody.\n".encode()
    code, _, _ = run_cli(["-o", str(out)], doc)
    assert code == 0 and "<title>Bom Title</title>" in out.read_text()


@pytest.mark.parametrize("ext", ["html", "pdf"])
def test_bug18_empty_image_src_vanishes(tmp_path, ext):
    code, _, err = run_cli(
        ["-o", str(tmp_path / f"o.{ext}")], b"# T\n\n![alt text](<>)\n"
    )
    assert code in (3, 4) and err.count("\n") == 1, err
