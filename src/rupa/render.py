"""Turn a Document into HTML or PDF bytes. All styling lives here and in themes/."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse

from jinja2 import Environment, select_autoescape
from pygments.formatters import HtmlFormatter

from .document import Document

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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

THEMES = ("default",)

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
        raise RenderError(f"unknown theme '{theme}' (have: {', '.join(THEMES)})")
    pkg = resources.files("rupa") / "themes"
    css = (pkg / f"{theme}.css").read_text(encoding="utf-8")
    if target == "pdf":
        css = _font_faces() + "\n" + css
        css += "\n" + (pkg / "print.css").read_text(encoding="utf-8")
    css += "\n" + HtmlFormatter(style="default").get_style_defs(".hl")
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
pre { padding: .6rem .8rem; }
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
pre { padding: .45rem .6rem; }
pre code { font-size: 7.8pt; }
""",
    ),
)


def to_html(
    doc: Document,
    theme: str = "default",
    target: str = "html",
    extra_css: str = "",
    toc_on: bool | None = None,
) -> str:
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
        body=doc.body_html,
        css=_theme_css(theme, target) + extra_css,
        target=target,
    )


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
        from weasyprint import HTML, URLFetcher
        from weasyprint.urls import FatalURLFetchingError
    except ImportError as exc:  # pragma: no cover - depends on system libs
        raise RenderError("PDF needs WeasyPrint and its system libraries") from exc

    base = Path(base_dir or ".").resolve()

    class ContainedFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            if url.startswith("file:"):
                path = Path(unquote(urlparse(url).path)).resolve()
                if not (path.is_relative_to(base) or path.parent == FONT_DIR):
                    raise ValueError(f"{path} is outside {base}")
            return super().fetch(url, headers)

    # Files under base, Rupa's own fonts, and data: URIs only. Anything else,
    # or a missing file, fails the render instead of fetching from the
    # network or vanishing.
    fetcher = ContainedFetcher(allowed_protocols={"file", "data"}, fail_on_errors=True)
    html = to_html(doc, theme, target="pdf", extra_css=extra_css, toc_on=toc_on)
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
    cut_words: int  # prose words to cut to fit, at the last step; 0 when it fits


# Prose at the tightest fit step holds about 1.49 words per point of page
# height, paragraph gaps included (measured on a full page of body text).
TIGHT_WORDS_PER_PT = 1.49


def _words_after(data: bytes, budget: int) -> int:
    """Prose words that would fill the space used past the budget.

    Measured as height rather than counted, because overflow is often code
    or a table, which take far more room per word than prose.
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
    return math.ceil(used * TIGHT_WORDS_PER_PT * 1.1)


def fit_pdf(
    doc: Document,
    theme: str = "default",
    base_dir: str | Path | None = None,
    budget: int | None = None,
) -> Fit:
    """Render a PDF, tightening it step by step until it fits `budget` pages.

    Content is never cut. If the tightest step is still over, the result
    says roughly how many words of prose to cut to free the space used past
    the budget.
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
    return Fit(data, pages, applied, _words_after(data, budget))
