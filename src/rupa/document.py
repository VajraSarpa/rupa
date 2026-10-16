"""Parse Markdown + YAML frontmatter into a Document model.

The model is the contract between Claude and Rupa: Claude writes plain
Markdown, Rupa owns every styling decision downstream of this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

ALLOWED_META = {"title", "subtitle", "author", "date", "theme", "toc"}


class InputError(ValueError):
    """Raised when the input cannot be turned into a Document."""


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
        "table"
    )
    md.use(front_matter_plugin)
    md.use(anchors_plugin, min_level=1, max_level=3)
    return md


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
            except yaml.YAMLError as exc:
                raise InputError(f"bad frontmatter: {exc}") from exc
            if not isinstance(loaded, dict):
                raise InputError("frontmatter must be a YAML mapping")
            unknown = set(loaded) - ALLOWED_META
            if unknown:
                raise InputError(
                    f"unknown frontmatter keys: {sorted(map(str, unknown))}"
                )
            meta = loaded
        elif tok.type == "heading_open":
            headings.append(
                Heading(
                    level=int(tok.tag[1]),
                    text=_plain_text(tokens[i + 1]),
                    anchor=tok.attrs.get("id", ""),
                )
            )

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
