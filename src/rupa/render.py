"""Turn a Document into HTML or PDF bytes. All styling lives here and in themes/."""

from __future__ import annotations

from importlib import resources

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


class RenderError(RuntimeError):
    """Raised when a target cannot be produced."""


def _theme_css(theme: str, target: str) -> str:
    if theme not in THEMES:
        raise RenderError(f"unknown theme '{theme}' (have: {', '.join(THEMES)})")
    pkg = resources.files("rupa") / "themes"
    css = (pkg / f"{theme}.css").read_text(encoding="utf-8")
    if target == "pdf":
        css += "\n" + (pkg / "print.css").read_text(encoding="utf-8")
    css += "\n" + HtmlFormatter(style="default").get_style_defs(".hl")
    return css


def to_html(doc: Document, theme: str = "default", target: str = "html") -> str:
    env = Environment(autoescape=select_autoescape(default=True))
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
        css=_theme_css(theme, target),
        target=target,
    )


def to_pdf(doc: Document, theme: str = "default") -> tuple[bytes, int]:
    """Return (pdf_bytes, page_count)."""
    try:
        from weasyprint import HTML, URLFetcher
        from weasyprint.urls import FatalURLFetchingError
    except ImportError as exc:  # pragma: no cover - depends on system libs
        raise RenderError("PDF needs WeasyPrint and its system libraries") from exc
    # Local files and data: URIs only. A remote URL fails the render instead of
    # silently fetching from the network.
    fetcher = URLFetcher(allowed_protocols={"file", "data"}, fail_on_errors=True)
    html = to_html(doc, theme, target="pdf")
    try:
        rendered = HTML(string=html, url_fetcher=fetcher).render()
        return rendered.write_pdf(), len(rendered.pages)
    except FatalURLFetchingError as exc:  # subclasses BaseException, not Exception
        raise RenderError(f"blocked or missing resource: {exc}") from exc
    except Exception as exc:  # keep the exit-4 contract for any WeasyPrint failure
        raise RenderError(f"PDF render failed: {exc}") from exc
