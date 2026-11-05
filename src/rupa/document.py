"""Parse Markdown + YAML frontmatter into a Document model.

The model is the contract between Claude and Rupa: Claude writes plain
Markdown, Rupa owns every styling decision downstream of this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import unquote

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

# Fenced blocks drawn as charts rather than shown as code.
CHART_LANGS = ("vega-lite", "vegalite")
ALLOWED_META = {"title", "subtitle", "author", "date", "theme", "toc", "pages"}
TEXT_META = ("title", "subtitle", "author", "date")
# A page budget no document comes near. YAML reads 0xFFF... ints of any
# size, and Python refuses to print one past 4,300 digits, so bigger
# budgets are capped here; a cap this high never changes a render.
MAX_PAGES = 100_000


class InputError(ValueError):
    """Raised when the input cannot be turned into a Document."""


def clip(value: object, limit: int = 80) -> str:
    """A value short enough to quote in a one-line error message."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def one_line(value: object) -> str:
    """A path or name for a status line: control characters escaped, so a
    newline in a file name can't split the one line stdout promises."""
    return _CONTROL.sub(lambda m: repr(m.group())[1:-1], str(value))


def show(value: object) -> str:
    """repr() for an error message, clipped; never raises.

    repr() of an int past 4,300 digits (or a list holding one) raises
    ValueError, and YAML reads such ints from a few kilobytes of hex.
    """
    try:
        return clip(repr(value))
    except ValueError:
        return f"a very large {type(value).__name__}"


def as_text(value: object) -> str:
    """str() that also works for an int past Python's 4,300-digit limit."""
    try:
        return str(value)
    except ValueError:
        return hex(value)  # only ints raise here; YAML read it as hex or octal


def yaml_problem(exc: Exception) -> str:
    # PyYAML's own message spans several lines with a source excerpt; keep
    # the problem and where it is.
    if isinstance(exc, yaml.MarkedYAMLError) and exc.problem:
        mark = exc.problem_mark
        where = f"line {mark.line + 1}, column {mark.column + 1}: " if mark else ""
        return where + exc.problem
    return clip(exc)


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that refuses aliases: a few lines of them, each repeating
    the last, expand into a page of megabytes."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.composer.ComposerError(
                None,
                None,
                "aliases (*name) are not allowed",
                self.peek_event().start_mark,
            )
        return super().compose_node(parent, index)


def _check_meta(meta: dict) -> dict:
    """Types the template and fitter rely on; text fields come back as str."""
    for key in TEXT_META:
        value = meta.get(key)
        if value is None:
            continue
        # A bare 2026 or 2026-10-17 in YAML is a number or a date, not a str.
        if isinstance(value, bool) or not isinstance(value, (str, int, float, date)):
            raise InputError(f"frontmatter '{key}' must be text, got {show(value)}")
        meta[key] = as_text(value)
    if "theme" in meta and not isinstance(meta["theme"], str):
        raise InputError(
            f"frontmatter 'theme' must be a theme name, got {show(meta['theme'])}"
        )
    for key in (*TEXT_META, "theme"):
        # A YAML "\uD800" escape gives a lone surrogate, which no output
        # format can encode.
        if isinstance(meta.get(key), str):
            try:
                meta[key].encode("utf-8")
            except UnicodeEncodeError as exc:
                raise InputError(
                    f"frontmatter '{key}' has a character that isn't valid"
                    f" Unicode ({show(exc.object[exc.start : exc.end])})"
                ) from exc
    if "toc" in meta and not isinstance(meta["toc"], bool):
        raise InputError(
            f"frontmatter 'toc' must be true or false, got {show(meta['toc'])}"
        )
    pages = meta.get("pages")
    if pages is not None and (
        not isinstance(pages, int) or isinstance(pages, bool) or pages < 1
    ):
        raise InputError("frontmatter 'pages' must be a whole number >= 1")
    if pages is not None:
        meta["pages"] = min(pages, MAX_PAGES)
    return meta


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
    # The body as markdown-it block tokens (no frontmatter, no repeated
    # title), for targets that don't go through HTML, such as DOCX.
    tokens: list = field(default_factory=list, repr=False)
    # Checked Vega-Lite specs from ```vega-lite blocks; each such fence token
    # carries meta["chart"], its index here.
    charts: list[dict] = field(default_factory=list, repr=False)

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
    md = MarkdownIt(
        "commonmark", {"html": False, "highlight": _highlight, "linkify": True}
    ).enable(["table", "strikethrough", "linkify"])
    # Bare URLs become links (never inside code), but only web and mail ones:
    # drop linkify-it's ftp: and protocol-relative // schemas.
    md.linkify.add("ftp:", None)
    md.linkify.add("//", None)
    md.use(front_matter_plugin)
    md.use(tasklists_plugin)
    md.use(footnote_plugin)
    md.use(anchors_plugin, min_level=1, max_level=3)

    # A chart block becomes an image placeholder that render.embed_images
    # fills with the drawn chart. The rupa-chart: scheme can't come from the
    # Markdown itself: _check_image refuses any image URL with a scheme.
    code_fence = md.renderer.rules["fence"]

    def fence(_self, tokens, idx, options, env):
        tok = tokens[idx]
        if "chart" in tok.meta:
            from html import escape

            from .charts import alt_text

            alt = escape(alt_text(env["charts"][tok.meta["chart"]]))
            return f'<p class="chart"><img src="rupa-chart:{tok.meta["chart"]}" alt="{alt}"></p>\n'
        return code_fence(tokens, idx, options, env)

    md.add_render_rule("fence", fence)
    # markdown-it drops a link or image whose URL it distrusts and leaves the
    # Markdown source in the page. Let every data:image URL through so
    # _check_image can refuse the ones Rupa can't render, with exit 3.
    md.validateLink = lambda url: (
        url.strip().lower().startswith("data:image/") or validateLink(url)
    )
    return md


_LINKIFY_HREF = re.compile(r"(https?://|mailto:)", re.IGNORECASE)
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
    if not src.strip():
        # markdown-it keeps ![alt](<>) as an image with no source, which
        # would show only its alt text, or nothing.
        raise InputError("an image has an empty source")
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
    if "\0" in unquote(src):  # %00: no file name holds one
        raise InputError(f"image '{clip(src)}' has a NUL (%00) in its path")


def _plain_text(inline) -> str:
    """Heading text without Markdown syntax: `**Big** `Plan`` -> 'Big Plan'."""
    parts = []
    for child in inline.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append(" ")
    return "".join(parts).strip()


def parse(text: str, *, html: bool = True) -> Document:
    """Parse Markdown into a Document. html=False skips rendering body_html
    (and Pygments), for targets that read doc.tokens instead."""
    if not text.strip():
        raise InputError("empty input: nothing to render")

    md = _build_parser()
    tokens = md.parse(text)

    meta: dict = {}
    headings: list[Heading] = []
    for i, tok in enumerate(tokens):
        if tok.type == "front_matter":
            try:
                loaded = yaml.load(tok.content, Loader=_NoAliasLoader) or {}
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
            meta = _check_meta(loaded)
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
                if child.markup == "linkify" and not _LINKIFY_HREF.match(href):
                    raise InputError(f"link '{clip(href)}' is not http(s) or mailto")
                # Only images may carry the data:image URLs let through above.
                if href.lower().startswith("data:") and not validateLink(href):
                    raise InputError(f"link '{clip(href)}' cannot be a data: URL")

    doc = Document(meta=meta, body_html="", headings=headings)
    for tok in tokens:
        if tok.type == "fence" and tok.info.strip().lower() in CHART_LANGS:
            from .charts import MAX_CHARTS, parse_block

            if len(doc.charts) >= MAX_CHARTS:
                raise InputError(f"more than {MAX_CHARTS} charts in one document")
            tok.meta["chart"] = len(doc.charts)
            doc.charts.append(parse_block(tok.content))
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

    doc.tokens = [t for t in tokens if t.type != "front_matter"]
    if not html:
        return doc
    body = md.renderer.render(tokens, md.options, {"charts": doc.charts})
    # Fenced code gets Pygments spans; mark the block for theme CSS.
    doc.body_html = re.sub(r"<pre><code", '<pre class="hl"><code', body)
    return doc
