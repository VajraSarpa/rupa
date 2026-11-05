"""Turn a Document into HTML or PDF bytes. All styling lives here and in themes/."""

from __future__ import annotations

import base64
import html as html_lib
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse

from jinja2 import Environment, select_autoescape
from pygments.formatters import HtmlFormatter

from .document import Document, clip

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="keywords" content="rupa-theme:{{ theme }}">
<title>{{ title }}</title>
<style>{{ css | safe }}</style>
</head>
<body class="{{ target }}">
<header class="cover">
  <h1 class="doc-title">{{ title }}</h1>
  {% if meta.subtitle %}<p class="subtitle">{{ meta.subtitle }}</p>{% endif %}
  {% if meta.author or meta.date %}
  <p class="byline">{{ meta.author or "" }}{% if meta.author and meta.date %} &middot; {% endif %}{{ meta.date or "" }}</p>
  {% endif %}
</header>
{% if toc %}
<nav class="toc"><h2>Contents</h2><ol>
{% for h in toc %}<li class="l{{ h.level }}"><a href="#{{ h.anchor }}">{{ h.text }}</a></li>
{% endfor %}</ol></nav>
{% endif %}
<main>
{{ body | safe }}
</main>
</body>
</html>
"""

THEMES = ("default", "cyan", "cyan-dark")
# A theme can share another's screen CSS and differ only in its print layer.
THEME_BASE = {"cyan-dark": "cyan"}
# The text colours verify accepts in a theme's PDFs. Light themes print solid
# black; a dark theme prints its own ink, accent and secondary greys.
THEME_TEXT_COLORS = {
    "default": ("#000000",),
    "cyan": ("#000000",),
    "cyan-dark": ("#e6edf6", "#38bdf8", "#9fb0c8", "#6b7d98"),
}

# Fonts ship with Rupa so a PDF looks the same on every machine, whatever is
# installed. Only the PDF target uses them; HTML keeps the CSS font stack.
FONT_DIR = Path(str(resources.files("rupa") / "themes" / "fonts")).resolve()
FONT_FACES = (  # (family, file stem, weight, style)
    ("Inter", "Inter-Regular", 400, "normal"),
    ("Inter", "Inter-Italic", 400, "italic"),
    ("Inter", "Inter-Medium", 500, "normal"),
    ("Inter", "Inter-SemiBold", 600, "normal"),
    ("Inter", "Inter-Bold", 700, "normal"),
    ("Inter", "Inter-BoldItalic", 700, "italic"),
    ("Hanken Grotesk", "HankenGrotesk-Regular", 400, "normal"),
    ("Hanken Grotesk", "HankenGrotesk-Italic", 400, "italic"),
    ("Hanken Grotesk", "HankenGrotesk-Medium", 500, "normal"),
    ("Hanken Grotesk", "HankenGrotesk-SemiBold", 600, "normal"),
    ("Hanken Grotesk", "HankenGrotesk-Bold", 700, "normal"),
    ("Hanken Grotesk", "HankenGrotesk-BoldItalic", 700, "italic"),
    ("JetBrains Mono", "JetBrainsMono-Regular", 400, "normal"),
    ("JetBrains Mono", "JetBrainsMono-Bold", 700, "normal"),
)


def _font_faces() -> str:
    return "\n".join(
        f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
        f'font-style: {style}; src: url("{(FONT_DIR / f"{stem}.ttf").as_uri()}"); }}'
        for family, stem, weight, style in FONT_FACES
    )


class RenderError(RuntimeError):
    """Raised when a target cannot be produced."""


def _theme_css(theme: str, target: str) -> str:
    if theme not in THEMES:
        raise RenderError(f"unknown theme '{clip(theme)}' (have: {', '.join(THEMES)})")
    pkg = resources.files("rupa") / "themes"
    css = (pkg / f"{THEME_BASE.get(theme, theme)}.css").read_text(encoding="utf-8")
    css += "\n" + HtmlFormatter(style="default").get_style_defs(".hl")
    if target == "pdf":
        # print.css goes last so it overrides Pygments' unscoped `pre` rule too,
        # then the theme's own print layer, if it has one.
        css = _font_faces() + "\n" + css
        css += "\n" + (pkg / "print.css").read_text(encoding="utf-8")
        layer = pkg / f"{theme}.print.css"
        if layer.is_file():
            css += "\n" + layer.read_text(encoding="utf-8")
    return css


# Steps for fitting a page budget, tried in order after the theme as written.
# Each changes only type size and spacing: page margins stay put (verify
# measures the body box from print.css) and headings stay at or above 11.5pt
# (verify detects headings by size).
FIT_STEPS = (
    ("no contents", None),
    (
        "compact type",
        """
body { font-size: 9.75pt; line-height: 1.42; }
.cover { margin-bottom: 1.1rem; padding-bottom: .8rem; }
h1 { margin: 1.8rem 0 .7rem; }
h2 { margin: 1.5rem 0 .55rem; }
h3 { margin: 1.1rem 0 .4rem; }
p, ul, ol { margin: 0 0 .65rem; }
li { margin: .1rem 0; }
table { margin: 0 0 .8rem; font-size: 8.75pt; }
th, td { padding: .3rem .5rem; }
pre { padding: .6rem .8rem; line-height: 13.12pt; }
""",
    ),
    (
        "tight type",
        """
body { font-size: 9pt; line-height: 1.32; }
.cover { margin-bottom: .8rem; padding-bottom: .6rem; }
h1 { margin: 1.2rem 0 .5rem; }
h2 { margin: 1rem 0 .4rem; padding-bottom: .2rem; }
h3 { margin: .8rem 0 .3rem; }
p, ul, ol { margin: 0 0 .45rem; }
li { margin: 0; }
table { margin: 0 0 .6rem; font-size: 8.25pt; }
th, td { padding: .2rem .4rem; }
pre { padding: .45rem .6rem; font-size: 7.8pt; line-height: 12.15pt; }
""",
    ),
)


_IMG_SRC = re.compile(r'(<img src=")([^"]+)(")')
# Raster images by the format Pillow detects from the bytes, not the name.
RASTER_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")


def _is_data_uri(src: str) -> bool:
    return src[:5].lower() == "data:"


def _decoded_mime(data: bytes, name: str, svg: bool = False) -> str:
    """The image's MIME type, once its bytes are known to decode as an image.

    A file that only claims to be an image (a renamed .env, a truncated PNG)
    fails here, so it is neither embedded in HTML nor dropped from a PDF.
    """
    if svg:
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise RenderError(f"image {name} is not valid SVG: {exc}") from exc
        if root.tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
            raise RenderError(f"image {name} is not an SVG image")
        for el in root.iter():
            for key in ("href", "{http://www.w3.org/1999/xlink}href"):
                ref = el.get(key, "").strip()
                if ref and not ref.startswith("#") and not _is_data_uri(ref):
                    raise RenderError(
                        f"image {name} links to '{clip(ref)}'; an SVG may use"
                        " only #ids and data: URIs"
                    )
        return "image/svg+xml"

    import io
    import warnings

    from PIL import Image, ImageFile

    # Importing WeasyPrint turns this on for the whole process, which would
    # let half a file through as an image.
    truncated_ok, ImageFile.LOAD_TRUNCATED_IMAGES = (
        ImageFile.LOAD_TRUNCATED_IMAGES,
        False,
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                fmt = img.format
                img.load()
    except Exception as exc:  # Pillow raises many types on bad data
        raise RenderError(f"image {name} cannot be decoded: {exc}") from exc
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = truncated_ok
    if fmt not in RASTER_MIME:
        raise RenderError(f"image {name} is {fmt}; use PNG, JPEG, GIF, WebP or SVG")
    return RASTER_MIME[fmt]


def load_image(src: str, base_dir: str | Path) -> tuple[bytes, str]:
    """Read one image the document names: (bytes, MIME type).

    A data: URI is decoded; a relative path must be an image file inside
    base_dir, not hidden (no part of it starts with '.'). Anything missing,
    refused or undecodable raises RenderError, so the render fails instead
    of leaving a broken image or embedding a file that isn't one.
    """
    if _is_data_uri(src):  # the scheme and ;base64 are case-insensitive
        header, _, payload = src.partition(",")
        try:
            data = (
                base64.b64decode(payload, validate=True)
                if header.lower().endswith(";base64")
                else unquote_to_bytes(payload)
            )
        except ValueError as exc:
            raise RenderError(f"image data URI cannot be decoded: {exc}") from exc
        svg = header.lower().startswith("data:image/svg+xml")
        return data, _decoded_mime(data, "data URI", svg=svg)

    base = Path(base_dir).resolve()
    if "\0" in unquote(src):  # resolve() raises ValueError on a NUL
        raise RenderError(f"blocked resource: '{clip(src)}' has a NUL in its path")
    path = (base / unquote(src)).resolve()
    if not path.is_relative_to(base):
        raise RenderError(f"blocked or missing resource: {path} is outside {base}")
    if any(part.startswith(".") for part in path.relative_to(base).parts):
        raise RenderError(f"blocked resource: {path} is a hidden file")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise RenderError(
            f"blocked resource: {path.name} is not an image"
            f" ({', '.join(IMAGE_SUFFIXES)})"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RenderError(f"blocked or missing resource: {path}") from exc
    return data, _decoded_mime(data, path.name, svg=path.suffix.lower() == ".svg")


def load_chart(
    src: str, base_dir: str | Path, charts=(), theme="default", target="html"
) -> tuple[bytes, str] | None:
    """A chart the page names, drawn as SVG; None if src isn't a chart.

    rupa-chart:N is the Nth ```vega-lite block (placed by document.parse);
    a .vl.json path is a spec file next to the Markdown.
    """
    if src.startswith("rupa-chart:"):
        spec = charts[int(src.split(":", 1)[1])]
    elif src.lower().endswith(".vl.json"):
        from .charts import load_chart_file

        spec = load_chart_file(src, base_dir)
    else:
        return None
    from .charts import to_svg

    return to_svg(spec, theme, target, base_dir), "image/svg+xml"


def embed_images(
    body: str, base_dir: str | Path, charts=(), theme="default", target="html"
) -> str:
    """Inline every image as a data: URI, so the page needs no other file.

    Each one goes through load_image first: only real images, only from
    inside base_dir. Charts are drawn here, as SVG.
    """

    def inline(m: re.Match) -> str:
        src = html_lib.unescape(m.group(2))
        chart = load_chart(src, base_dir, charts, theme, target)
        data, mime = chart or load_image(src, base_dir)
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        return m.group(1) + uri + m.group(3)

    return _IMG_SRC.sub(inline, body)


def to_html(
    doc: Document,
    theme: str = "default",
    target: str = "html",
    extra_css: str = "",
    toc_on: bool | None = None,
    base_dir: str | Path | None = None,
) -> str:
    """Return the page as HTML. With base_dir, images are embedded (see embed_images)."""
    env = Environment(autoescape=select_autoescape(default=True))
    if toc_on is None:
        toc_on = doc.meta.get("toc", True)
    # H1s act as parts, H2s as sections. An H1 that repeats the title is skipped.
    toc = (
        [h for h in doc.headings if h.level <= 2 and h.text != doc.title]
        if toc_on
        else []
    )
    return env.from_string(TEMPLATE).render(
        title=doc.title,
        meta=doc.meta,
        toc=toc,
        body=(
            embed_images(doc.body_html, base_dir or ".", doc.charts, theme, target)
            if base_dir or doc.charts
            else doc.body_html
        ),
        css=_theme_css(theme, target) + extra_css,
        target=target,
        theme=theme,
    )


def contained_fetcher(base: Path):
    """A WeasyPrint URL fetcher for data: URIs and Rupa's bundled fonts only.

    Images arrive already checked by load_image and inlined, since WeasyPrint
    swaps an image it can't decode for its alt text, so nothing else needs a
    file. That also stops an SVG's own <image href="file:..."> (any case)
    from reading a file load_image would refuse. Anything else, or a missing
    font, fails the render instead of fetching from the network or vanishing.
    `base` names the document's folder in the error.
    """
    try:
        from weasyprint import URLFetcher
    except ImportError as exc:  # pragma: no cover - depends on system libs
        raise RenderError("PDF needs WeasyPrint and its system libraries") from exc

    class ContainedFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            scheme = urlparse(url).scheme.lower()
            if scheme == "file":
                path = Path(unquote(urlparse(url).path)).resolve()
                if path.parent != FONT_DIR or path.suffix != ".ttf":
                    raise ValueError(
                        f"{clip(str(path))} is not an image Rupa inlined from {base}"
                    )
            elif scheme != "data":
                raise ValueError(f"{clip(url)} is not a local resource")
            return super().fetch(url, headers)

    return ContainedFetcher(allowed_protocols={"file", "data"}, fail_on_errors=True)


def to_pdf(
    doc: Document,
    theme: str = "default",
    base_dir: str | Path | None = None,
    extra_css: str = "",
    toc_on: bool | None = None,
) -> tuple[bytes, int]:
    """Return (pdf_bytes, page_count).

    Relative image paths resolve against base_dir (default: the current
    directory), and only files inside it can be read.
    """
    try:
        from weasyprint import HTML
        from weasyprint.urls import FatalURLFetchingError
    except ImportError as exc:  # pragma: no cover - depends on system libs
        raise RenderError("PDF needs WeasyPrint and its system libraries") from exc

    base = Path(base_dir or ".").resolve()
    fetcher = contained_fetcher(base)
    html = to_html(
        doc, theme, target="pdf", extra_css=extra_css, toc_on=toc_on, base_dir=base
    )
    try:
        rendered = HTML(
            string=html, base_url=f"{base.as_uri()}/", url_fetcher=fetcher
        ).render()
        return rendered.write_pdf(), len(rendered.pages)
    except FatalURLFetchingError as exc:  # subclasses BaseException, not Exception
        raise RenderError(f"blocked or missing resource: {exc}") from exc
    except Exception as exc:  # keep the exit-4 contract for any WeasyPrint failure
        raise RenderError(f"PDF render failed: {exc}") from exc


@dataclass
class Fit:
    data: bytes
    pages: int
    steps: list[str]  # fit steps applied, in order; empty if none were needed
    cut_lines: int  # lines to cut to fit, at the last step; 0 when it fits


# At the tightest fit step a line takes about 12.4pt of page height, paragraph
# gaps included, and a line of prose holds about 18 words (measured on full
# pages of body text and of code).
TIGHT_LINE_PT = 12.4
PROSE_WORDS_PER_LINE = 18


def _lines_after(data: bytes, budget: int) -> int:
    """Lines of content to cut so the space used past the budget fits.

    Counted in lines, not words: overflow is often code or a table, where a
    line holds one or two words, so a word count asks for far too little
    there and far too much when prose is cut instead.
    """
    import io
    import math

    import pdfplumber

    from .verify import FOOTER_CUTOFF, MARGIN_TOP, PT_PER_IN

    used = 0.0
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[budget:]:
            footer = page.height - FOOTER_CUTOFF * PT_PER_IN
            body = [c["bottom"] for c in page.chars if c["bottom"] < footer]
            if body:
                used += max(body) - MARGIN_TOP * PT_PER_IN
    # 10% over, since blocks that can't split (rows, short code) break late.
    return math.ceil(used / TIGHT_LINE_PT * 1.1)


def fit_pdf(
    doc: Document,
    theme: str = "default",
    base_dir: str | Path | None = None,
    budget: int | None = None,
) -> Fit:
    """Render a PDF, tightening it step by step until it fits `budget` pages.

    Content is never cut. If the tightest step is still over, the result
    says roughly how many lines to cut to free the space used past the
    budget.
    """
    data, pages = to_pdf(doc, theme, base_dir)
    if not budget or pages <= budget:
        return Fit(data, pages, [], 0)
    applied: list[str] = []
    css = ""
    toc_on = doc.meta.get("toc", True)
    for name, step_css in FIT_STEPS:
        if step_css is None:
            if not toc_on:
                continue
            toc_on = False
        else:
            css = step_css
        applied.append(name)
        data, pages = to_pdf(doc, theme, base_dir, extra_css=css, toc_on=toc_on)
        if pages <= budget:
            return Fit(data, pages, applied, 0)
    return Fit(data, pages, applied, _lines_after(data, budget))
