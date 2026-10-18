"""Parse Markdown + YAML frontmatter into a Document model.

The model is the contract between Claude and Rupa: Claude writes plain
Markdown, Rupa owns every styling decision downstream of this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from markdown_it import MarkdownIt
from markdown_it.common.normalize_url import validateLink
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

ALLOWED_META = {"title", "subtitle", "author", "date", "theme", "toc", "pages"}


class InputError(ValueError):
    """Raised when the input cannot be turned into a Document."""


def clip(value: object, limit: int = 80) -> str:
    """A value short enough to quote in a one-line error message."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def yaml_problem(exc: Exception) -> str:
    # PyYAML's own message spans several lines with a source excerpt; keep
    # the problem and where it is.
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem:
        mark = exc.problem_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        return where + exc.problem
    return clip(exc)


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


@dataclass
class Document:
    meta: dict
    body_html: str
    headings: list[Heading] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.meta.get("title"):
            return str(self.meta["title"])
        return self.headings[0].text if self.headings else "Untitled"


def _highlight(code: str, lang: str, _attrs: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def _build_parser() -> MarkdownIt:
    # html=False: raw HTML in the input is escaped, never passed through.
    md = MarkdownIt("commonmark", {"html": False, "highlight": _highlight}).enable(
        ["table", "strikethrough"]
    )
    md.use(front_matter_plugin)
    md.use(tasklists_plugin)
    md.use(footnote_plugin)
    md.use(anchors_plugin, min_level=1, max_level=3)
    # markdown-it drops a link or image whose URL it distrusts and leaves the
    # Markdown source in the page. Let every data:image URL through so
    # _check_image can refuse the ones Rupa can't render, with exit 3.
    md.validateLink = lambda url: (
        url.strip().lower().startswith("data:image/") or validateLink(url)
    )
    return md


_SCHEME = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*:")

# The data:image types render.load_image can decode.
DATA_IMAGE_TYPES = ("png", "jpeg", "gif", "webp", "svg+xml")


def data_image_type(src: str) -> str:
    """'svg+xml' for 'data:image/svg+xml;base64,...'."""
    return src[len("data:image/") :].split(",")[0].split(";")[0].strip().lower()


def _check_image(src: str) -> None:
    """Images are relative paths or inline data, never fetched from elsewhere.

    A remote image in the HTML would be fetched by the reader's browser, which
    leaks that the page was opened and anything put in the URL.
    """
    if src.lower().startswith("data:image/"):
        if data_image_type(src) not in DATA_IMAGE_TYPES:
            raise InputError(
                f"image '{clip(src)}' is not a data:image type Rupa renders"
                f" ({', '.join(DATA_IMAGE_TYPES)})"
            )
        return
    if _SCHEME.match(src) or src.startswith(("/", "\\")):
        raise InputError(
            f"image '{clip(src)}' must be a relative path or a data:image URI"
        )


def _plain_text(inline) -> str:
    """Heading text without Markdown syntax: `**Big** `Plan`` -> 'Big Plan'."""
    parts = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts).strip()


def parse(text: str) -> Document:
    if not text.strip():
        raise InputError("empty input: nothing to render")

    md = _build_parser()
    tokens = md.parse(text)

    meta: dict = {}
    headings: list[Heading] = []
    for i, tok in enumerate(tokens):
        if tok.type == "front_matter":
            try:
                loaded = yaml.safe_load(tok.content) or {}
            # An impossible date (2026-02-30) raises ValueError, and deeply
            # nested YAML RecursionError; both are bad input, not a crash.
            except (yaml.YAMLError, ValueError, OverflowError, RecursionError) as exc:
                raise InputError(f"bad frontmatter: {yaml_problem(exc)}") from exc
            if not isinstance(loaded, dict):
                raise InputError("frontmatter must be a YAML mapping")
            unknown = set(loaded) - ALLOWED_META
            if unknown:
                raise InputError(
                    f"unknown frontmatter keys: {clip(sorted(map(str, unknown)))}"
                )
            pages = loaded.get("pages")
            if pages is not None and (
                not isinstance(pages, int) or isinstance(pages, bool) or pages < 1
            ):
                raise InputError("frontmatter 'pages' must be a whole number >= 1")
            meta = loaded
        elif tok.type == "heading_open":
            headings.append(
                Heading(
                    level=int(tok.tag[1]),
                    text=_plain_text(tokens[i + 1]),
                    anchor=tok.attrs.get("id", ""),
                )
            )

    for tok in tokens:
        for child in tok.children or []:
            if child.type == "image":
                _check_image(str(child.attrs.get("src", "")))
            elif child.type == "link_open":
                href = str(child.attrs.get("href", ""))
                # Only images may carry the data:image URLs let through above.
                if href.lower().startswith("data:") and not validateLink(href):
                    raise InputError(f"link '{clip(href)}' cannot be a data: URL")

    doc = Document(meta=meta, body_html="", headings=headings)
    # The cover already shows the title, so a leading H1 that repeats it is
    # dropped from the body. Any other leading H1 is a real part and stays.
    first = next((i for i, t in enumerate(tokens) if t.type != "front_matter"), None)
    if (
        first is not None
        and tokens[first].type == "heading_open"
        and tokens[first].tag == "h1"
        and _plain_text(tokens[first + 1]) == doc.title
    ):
        del tokens[first : first + 3]

    body = md.renderer.render(tokens, md.options, {})
    # Fenced code gets Pygments spans; mark the block for theme CSS.
    doc.body_html = re.sub(r"<pre><code", '<pre class="hl"><code', body)
    return doc
