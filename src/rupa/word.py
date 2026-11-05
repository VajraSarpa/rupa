"""Turn a Document into DOCX bytes.

WordprocessingML is written directly from the markdown-it tokens: no
template file, no extra dependency, and the same input always gives the
same bytes (fixed zip timestamps, no creation dates or user names).

What goes into the package, and what never does:

- Text is solid black (#000000) in every theme; a theme sets fonts and the
  colour of rules and borders only.
- Images go through render.load_image, the same guard as HTML and PDF: only
  real images from inside the input's folder, or data: URIs. SVG and WebP
  are rasterised to PNG here, so no SVG (which can name other files or URLs)
  ever reaches Word.
- Hyperlinks are http, https and mailto, or a #heading inside the document.
  Any other link (a relative file, file:, a custom scheme) keeps its text and
  loses the link, so opening the document never opens a local file.
- No macros, fields that ask to update, external templates, embedded
  objects, or remote resources. The only fields are PAGE and NUMPAGES in the
  footer.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

from . import __version__
from .document import Document
from .render import THEMES, RenderError, load_image

# --- page geometry (Letter, the margins print.css gives the PDF) ----------

TWIP_PER_IN = 1440
EMU_PER_IN = 914400
PAGE_W, PAGE_H = 12240, 15840
MARGIN_TOP, MARGIN_SIDE, MARGIN_BOTTOM = 1224, 1152, 1296  # .85in .8in .9in
TEXT_W = PAGE_W - 2 * MARGIN_SIDE  # 6.9in
TEXT_W_EMU = TEXT_W * EMU_PER_IN // TWIP_PER_IN
MAX_IMAGE_H_EMU = int(8.5 * EMU_PER_IN)  # leaves room for a line around it
LIST_INDENT = 360  # twips per list or quote level
WIDE_TABLE_COLS = 9  # as in the PDF theme, set in smaller type from here
SVG_MAX_PX = 2000  # cap on an SVG's drawn size before rasterising
SVG_SCALE = 2  # raster pixels per CSS pixel, for a sharp print


@dataclass(frozen=True)
class WordTheme:
    body: str
    heading: str
    mono: str
    accent: str  # rules and borders only; text is always black
    rule: str
    code_bg: str


WORD_THEMES = {
    "default": WordTheme(
        "Inter", "Inter", "JetBrains Mono", "0E7490", "94A3B8", "F1F5F9"
    ),
    "cyan": WordTheme(
        "Hanken Grotesk",
        "Hanken Grotesk",
        "JetBrains Mono",
        "38BDF8",
        "D3DDE8",
        "F5F9FC",
    ),
}
# Word has no dark page that prints, so cyan-dark is cyan on paper.
WORD_THEMES["cyan-dark"] = WORD_THEMES["cyan"]
assert set(WORD_THEMES) == set(THEMES), "every theme needs a Word mapping"

# What Word substitutes when a theme font isn't installed.
FONT_FALLBACK = {
    "Inter": ("Arial", "swiss", "variable"),
    "Hanken Grotesk": ("Arial", "swiss", "variable"),
    "JetBrains Mono": ("Courier New", "modern", "fixed"),
}

# --- XML helpers -----------------------------------------------------------

# Characters XML 1.0 forbids; Word refuses a file that contains one.
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")


def esc(text: str) -> str:
    return _xml_escape(_XML_BAD.sub("", text))


def attr(text: str) -> str:
    return _xml_escape(_XML_BAD.sub("", text), {'"': "&quot;", "\n": " "})


NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_IMAGE = f"{REL}/image"
REL_LINK = f"{REL}/hyperlink"
SAFE_LINK = re.compile(r"(?i)^(https?://|mailto:)")
_TASK_BOX = re.compile(r'class="task-list-item-checkbox"')


class _Rels:
    """The relationships of one part (document.xml or footnotes.xml)."""

    def __init__(self, fixed: list[tuple[str, str]] = ()):
        self.items: list[tuple[str, str, str, bool]] = []  # id, type, target, ext
        self._seen: dict[tuple[str, str], str] = {}
        for rtype, target in fixed:
            self.add(rtype, target)

    def add(self, rtype: str, target: str, external: bool = False) -> str:
        key = (rtype, target)
        if key not in self._seen:
            rid = f"rId{len(self.items) + 1}"
            self.items.append((rid, rtype, target, external))
            self._seen[key] = rid
        return self._seen[key]

    def xml(self) -> str:
        rows = "".join(
            f'<Relationship Id="{rid}" Type="{rtype}" Target="{attr(target)}"'
            + (' TargetMode="External"' if ext else "")
            + "/>"
            for rid, rtype, target, ext in self.items
        )
        return (
            XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/'
            f'package/2006/relationships">{rows}</Relationships>'
        )


def _bookmark_names(anchors: list[str]) -> dict[str, str]:
    """Word bookmark names for heading anchors: hidden (leading _), letters,
    digits and _ only, at most 40 characters, unique."""
    names: dict[str, str] = {}
    used: set[str] = set()
    for anchor in anchors:
        if not anchor or anchor in names:
            continue
        base = "_r_" + re.sub(r"[^A-Za-z0-9_]", "_", anchor)[:34]
        name, n = base, 1
        while name in used:
            n += 1
            name = f"{base[: 40 - len(str(n)) - 1]}_{n}"
        used.add(name)
        names[anchor] = name
    return names


def _plain(children) -> str:
    out = []
    for c in children or []:
        if c.type in ("text", "code_inline"):
            out.append(c.content)
        elif c.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif c.children:
            out.append(_plain(c.children))
    return "".join(out).strip()


# --- images ----------------------------------------------------------------


def _svg_size(data: bytes) -> tuple[float, float]:
    """An SVG's drawn size in CSS pixels, as a browser would size an <img>."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(data)
    units = {"": 1, "px": 1, "pt": 4 / 3, "pc": 16, "in": 96, "cm": 96 / 2.54}
    units["mm"] = units["cm"] / 10

    def length(value: str | None) -> float | None:
        m = re.fullmatch(r"\s*([0-9.]+)\s*(px|pt|pc|in|cm|mm)?\s*", value or "")
        if not m:
            return None
        try:
            return float(m.group(1)) * units[m.group(2) or ""]
        except ValueError:
            return None

    w, h = length(root.get("width")), length(root.get("height"))
    box = (root.get("viewBox") or "").replace(",", " ").split()
    vw = vh = None
    if len(box) == 4:
        try:
            vw, vh = float(box[2]), float(box[3])
        except ValueError:
            pass
    if vw and vh and vw > 0 and vh > 0:
        if w and not h:
            h = w * vh / vw
        elif h and not w:
            w = h * vw / vh
        elif not w and not h:
            w, h = vw, vh
    w, h = w or 300, h or 150  # a browser's default replaced-element size
    scale = min(1, SVG_MAX_PX / max(w, h))
    return max(1, w * scale), max(1, h * scale)


def _svg_to_png(data: bytes, base: Path) -> tuple[bytes, float, float]:
    """Rasterise an SVG offline: (PNG bytes, width px, height px).

    WeasyPrint draws it with the same contained fetcher as the PDF, so the
    SVG can't reach the network or a file outside the input's folder.
    """
    import base64

    from .render import contained_fetcher

    try:
        import pypdfium2
        from weasyprint import HTML
        from weasyprint.urls import FatalURLFetchingError
    except ImportError as exc:  # pragma: no cover - depends on system libs
        raise RenderError("SVG in DOCX needs WeasyPrint and pypdfium2") from exc

    w, h = _svg_size(data)
    uri = "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")
    page = (
        f"<style>@page {{ size: {w}px {h}px; margin: 0 }} html, body {{ margin: 0 }}"
        f" img {{ display: block; width: {w}px; height: {h}px }}</style>"
        f'<img src="{uri}">'
    )
    try:
        pdf_bytes = HTML(
            string=page,
            base_url=f"{base.as_uri()}/",
            url_fetcher=contained_fetcher(base),
        ).write_pdf()
        pdf = pypdfium2.PdfDocument(pdf_bytes)
        try:
            bitmap = pdf[0].render(scale=SVG_SCALE * 96 / 72)
            out = io.BytesIO()
            bitmap.to_pil().save(out, format="PNG", optimize=True)
        finally:
            pdf.close()
    except FatalURLFetchingError as exc:
        raise RenderError(f"blocked or missing resource in SVG: {exc}") from exc
    except Exception as exc:
        raise RenderError(f"SVG could not be drawn: {exc}") from exc
    return out.getvalue(), w, h


def _raster_info(data: bytes) -> tuple[str, float, float, bytes]:
    """(extension, width in, height in, bytes) for an image already decoded
    once by load_image. WebP becomes PNG, which every Word opens."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        dpi = img.info.get("dpi") or (96, 96)
        dx = dpi[0] if dpi[0] and dpi[0] > 1 else 96
        dy = dpi[1] if dpi[1] and dpi[1] > 1 else 96
        w_in, h_in = img.width / dx, img.height / dy
        if fmt == "WEBP":
            out = io.BytesIO()
            frame = img.convert("RGBA") if img.mode not in ("RGB", "RGBA") else img
            frame.save(out, format="PNG", optimize=True)
            return "png", w_in, h_in, out.getvalue()
    return {"PNG": "png", "JPEG": "jpeg", "GIF": "gif"}[fmt], w_in, h_in, data


def _fit_emu(w_in: float, h_in: float) -> tuple[int, int]:
    cx, cy = w_in * EMU_PER_IN, h_in * EMU_PER_IN
    scale = min(1.0, TEXT_W_EMU / cx if cx else 1, MAX_IMAGE_H_EMU / cy if cy else 1)
    return max(1, int(cx * scale)), max(1, int(cy * scale))


# --- the body --------------------------------------------------------------


class _Writer:
    def __init__(self, doc: Document, theme: WordTheme, base: Path, theme_name: str):
        self.doc, self.theme, self.base = doc, theme, base
        self.theme_name = theme_name
        self.bookmarks = _bookmark_names([h.anchor for h in doc.headings])
        self._bm_id = 0
        self._pic_id = 0
        self.media: dict[str, bytes] = {}  # zip path -> bytes
        self._media_by_hash: dict[str, tuple[str, int, int]] = {}
        self.nums: list[tuple[int, int]] = []  # (abstractNumId, start), numId = i+1
        self.footnotes: list[tuple[int, str]] = []
        self._fn_tokens: dict[int, list] = {}
        # Block context
        self.lists: list[dict] = []
        self.quote = 0
        self.break_next = False
        self.in_footnote: int | None = None

    # -- runs ---------------------------------------------------------------

    def _rpr(self, *, style=None, mono=False, bold=False, italic=False,
             strike=False, sz=None, sym=False) -> str:  # fmt: skip
        parts = []
        if style:
            parts.append(f'<w:rStyle w:val="{style}"/>')
        if sym:
            parts.append(
                '<w:rFonts w:ascii="Segoe UI Symbol" w:hAnsi="Segoe UI Symbol"/>'
            )
        elif mono:
            m = attr(self.theme.mono)
            parts.append(f'<w:rFonts w:ascii="{m}" w:hAnsi="{m}" w:cs="{m}"/>')
        if bold:
            parts.append("<w:b/><w:bCs/>")
        if italic:
            parts.append("<w:i/><w:iCs/>")
        if strike:
            parts.append("<w:strike/>")
        if sz:
            parts.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
        return f"<w:rPr>{''.join(parts)}</w:rPr>" if parts else ""

    @staticmethod
    def _run(text: str, rpr: str = "") -> str:
        pieces = []
        for i, line in enumerate(text.split("\n")):
            if i:
                pieces.append("<w:br/>")
            for j, chunk in enumerate(line.split("\t")):
                if j:
                    pieces.append("<w:tab/>")
                if chunk:
                    pieces.append(f'<w:t xml:space="preserve">{esc(chunk)}</w:t>')
        return f"<w:r>{rpr}{''.join(pieces)}</w:r>" if pieces else ""

    def _runs(self, children, rels: _Rels, *, bold=0, sz=None) -> str:
        parts: list[str] = []
        italic = strike = 0
        link: tuple[int, str] | None = None
        for c in children or []:
            t = c.type
            fmt = {
                "bold": bold > 0,
                "italic": italic > 0,
                "strike": strike > 0,
                "sz": sz,
            }
            if link:
                fmt["style"] = "Hyperlink"
            if t == "text":
                parts.append(self._run(c.content, self._rpr(**fmt)))
            elif t == "code_inline":
                fmt["style"] = "CodeChar"
                parts.append(self._run(c.content, self._rpr(**fmt)))
            elif t == "softbreak":
                parts.append(self._run(" ", self._rpr(**fmt)))
            elif t == "hardbreak":
                parts.append("<w:r><w:br/></w:r>")
            elif t == "strong_open":
                bold += 1
            elif t == "strong_close":
                bold -= 1
            elif t == "em_open":
                italic += 1
            elif t == "em_close":
                italic -= 1
            elif t == "s_open":
                strike += 1
            elif t == "s_close":
                strike -= 1
            elif t == "link_open":
                target = self._link(str(c.attrs.get("href", "")), rels)
                link = (len(parts), target) if target else None
            elif t == "link_close":
                if link:
                    start, target = link
                    inner = "".join(parts[start:])
                    del parts[start:]
                    parts.append(f"<w:hyperlink {target}>{inner}</w:hyperlink>")
                link = None
            elif t == "image":
                parts.append(self._image(c, rels))
            elif t == "footnote_ref":
                parts.append(self._footnote_ref(c.meta))
            elif t == "footnote_anchor":
                continue  # the HTML back-link; Word links the number itself
            elif t == "html_inline" and _TASK_BOX.search(c.content):
                box = "☒" if 'checked="checked"' in c.content else "☐"
                parts.append(self._run(box, self._rpr(sym=True, sz=sz)))
            else:  # anything else is shown as its text, never as markup
                parts.append(self._run(c.content, self._rpr(**fmt)))
        return "".join(parts)

    def _link(self, href: str, rels: _Rels) -> str | None:
        if href.startswith("#"):
            name = self.bookmarks.get(href[1:])
            return f'w:anchor="{attr(name)}" w:history="1"' if name else None
        if SAFE_LINK.match(href):
            rid = rels.add(REL_LINK, href, external=True)
            return f'r:id="{rid}" w:history="1"'
        return None

    def _footnote_ref(self, meta: dict) -> str:
        n = int(meta["id"]) + 1
        if meta.get("subId", 0):  # Word can't point at one footnote twice
            return self._run(
                str(n), '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
            )
        return (
            '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
            f'<w:footnoteReference w:id="{n}"/></w:r>'
        )

    def _image(self, tok, rels: _Rels) -> str:
        src = str(tok.attrs.get("src", ""))
        if src.lower().endswith(".vl.json"):
            from .charts import load_chart_file

            spec = load_chart_file(src, self.base)
            return self._chart_run(spec, _plain(tok.children) or tok.content, rels)
        data, mime = load_image(src, self.base)  # the shared image guard
        if mime == "image/svg+xml":
            data, w_px, h_px = _svg_to_png(data, self.base)
            ext, size = "png", (w_px / 96, h_px / 96)
        else:
            ext, w_in, h_in, data = _raster_info(data)
            size = (w_in, h_in)
        return self._drawing(data, ext, size, _plain(tok.children) or tok.content, rels)

    def _chart_run(self, spec: dict, alt: str, rels: _Rels) -> str:
        from .charts import to_png

        data, w_px, h_px = to_png(spec, self.theme_name, self.base)
        return self._drawing(data, "png", (w_px / 96, h_px / 96), alt, rels)

    def _chart(self, index: int, rels: _Rels) -> str:
        from .charts import alt_text

        spec = self.doc.charts[index]
        run = self._chart_run(spec, alt_text(spec), rels)
        ppr = self._ppr(None)
        if self.lists:
            self.lists[-1]["pending"] = False
        return f"<w:p>{ppr}{run}</w:p>"

    def _drawing(self, data: bytes, ext: str, size, alt: str, rels: _Rels) -> str:
        key = hashlib.sha256(data).hexdigest()
        if key not in self._media_by_hash:
            path = f"media/image{len(self.media) + 1}.{ext}"
            self.media[path] = data
            self._media_by_hash[key] = (path, *_fit_emu(*size))
        path, cx, cy = self._media_by_hash[key]
        rid = rels.add(REL_IMAGE, path)
        self._pic_id += 1
        n = self._pic_id
        alt = attr(alt)
        return (
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{n}" name="Picture {n}" descr="{alt}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/>'
            "</wp:cNvGraphicFramePr><a:graphic>"
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="{path[6:]}" descr="{alt}"/>'
            "<pic:cNvPicPr/></pic:nvPicPr>"
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/>'
            "</a:stretch></pic:blipFill>"
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
            '</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>"
        )

    # -- paragraphs ---------------------------------------------------------

    def _ppr(self, style: str | None, *, numbered=False, jc=None, extra="") -> str:
        """Paragraph properties, with the list and quote context applied."""
        parts = []
        if self.in_footnote is not None and style in (None, "Normal"):
            style = "FootnoteText"
        if style:
            parts.append(f'<w:pStyle w:val="{style}"/>')
        if self.break_next:
            parts.append("<w:pageBreakBefore/>")
            self.break_next = False
        lvl = len(self.lists) - 1
        if numbered:
            num_id = self.lists[-1]["num"]
            parts.append(
                f'<w:numPr><w:ilvl w:val="{min(lvl, 8)}"/>'
                f'<w:numId w:val="{num_id}"/></w:numPr>'
            )
        parts.append(extra)
        if self.lists or self.quote:
            left = (self.quote + lvl + 1) * LIST_INDENT
            hanging = f' w:hanging="{LIST_INDENT}"' if numbered else ""
            parts.append(f'<w:ind w:left="{left}"{hanging}/>')
        if jc:
            parts.append(f'<w:jc w:val="{jc}"/>')
        return f"<w:pPr>{''.join(parts)}</w:pPr>"

    def _para(self, children, rels: _Rels, style=None, extra="") -> str:
        numbered = False
        if self.lists and self.lists[-1]["pending"]:
            numbered = self.lists[-1]["num"] is not None
        if self.quote and style is None and not self.lists:
            style = "Quote"
        ppr = self._ppr(style, numbered=numbered, extra=extra)
        if self.lists:
            self.lists[-1]["pending"] = False
        lead = ""
        if self.in_footnote is not None and self._fn_first:
            lead = (
                '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                '<w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> </w:t></w:r>'
            )
            self._fn_first = False
        return f"<w:p>{ppr}{lead}{self._runs(children, rels)}</w:p>"

    def _heading(self, tok, inline, rels: _Rels) -> str:
        level = int(tok.tag[1])
        anchor = str(tok.attrs.get("id", ""))
        ppr = self._ppr(f"Heading{level}")
        body = self._runs(inline.children, rels)
        name = self.bookmarks.get(anchor)
        if name and self.in_footnote is None:
            self._bm_id += 1
            body = (
                f'<w:bookmarkStart w:id="{self._bm_id}" w:name="{attr(name)}"/>'
                f'{body}<w:bookmarkEnd w:id="{self._bm_id}"/>'
            )
        return f"<w:p>{ppr}{body}</w:p>"

    def _code(self, content: str) -> str:
        text = content.removesuffix("\n")
        ppr = self._ppr("Code")
        if self.lists:
            self.lists[-1]["pending"] = False
        return f"<w:p>{ppr}{self._run(text) or '<w:r/>'}</w:p>"

    def _table(self, tokens, i, rels: _Rels) -> tuple[str, int]:
        rows: list[list[tuple[bool, str | None, list]]] = []
        while tokens[i].type != "table_close":
            t = tokens[i]
            if t.type == "tr_open":
                rows.append([])
            elif t.type in ("th_open", "td_open"):
                style = str(t.attrs.get("style", ""))
                m = re.search(r"text-align:(left|center|right)", style)
                align = {"left": "left", "center": "center", "right": "right"}.get(
                    m.group(1) if m else ""
                )
                rows[-1].append((t.type == "th_open", align, tokens[i + 1].children))
            i += 1
        ncols = max((len(r) for r in rows), default=1)
        sz = 15 if ncols >= WIDE_TABLE_COLS else 18
        col_w = TEXT_W // ncols
        th = self.theme
        border = f'w:val="single" w:sz="4" w:space="0" w:color="{th.rule}"'
        head_rule = f'w:val="single" w:sz="12" w:space="0" w:color="{th.accent}"'
        out = []
        if self.break_next:
            out.append(f"<w:p>{self._ppr(None)}</w:p>")
        out.append(
            "<w:tbl><w:tblPr>"
            '<w:tblW w:w="5000" w:type="pct"/>'
            f"<w:tblBorders><w:top {border}/><w:bottom {border}/>"
            f"<w:insideH {border}/></w:tblBorders>"
            '<w:tblCellMar><w:top w:w="40" w:type="dxa"/>'
            '<w:left w:w="100" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/>'
            '<w:right w:w="100" w:type="dxa"/></w:tblCellMar>'
            '<w:tblLook w:val="0420" w:firstRow="1" w:lastRow="0" w:firstColumn="0"'
            ' w:lastColumn="0" w:noHBand="1" w:noVBand="1"/>'
            "</w:tblPr><w:tblGrid>"
            + "".join(f'<w:gridCol w:w="{col_w}"/>' for _ in range(ncols))
            + "</w:tblGrid>"
        )
        for row in rows:
            head = bool(row) and row[0][0]
            trpr = "<w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if head else "")
            out.append(f"<w:tr>{trpr}</w:trPr>")
            cells = row + [(head, None, [])] * (ncols - len(row))
            for is_head, align, children in cells:
                tcb = (
                    f"<w:tcBorders><w:bottom {head_rule}/></w:tcBorders>"
                    if is_head
                    else ""
                )
                jc = f'<w:jc w:val="{align}"/>' if align else ""
                runs = self._runs(children, rels, bold=int(is_head), sz=sz)
                out.append(
                    f'<w:tc><w:tcPr><w:tcW w:w="{col_w}" w:type="dxa"/>{tcb}</w:tcPr>'
                    f'<w:p><w:pPr><w:pStyle w:val="TableText"/>{jc}'
                    f'<w:rPr><w:sz w:val="{sz}"/></w:rPr></w:pPr>{runs}</w:p></w:tc>'
                )
            out.append("</w:tr>")
        out.append("</w:tbl>")
        # Two tables in a row would merge into one in Word; a paragraph
        # between them keeps them apart and gives the table its bottom gap.
        out.append('<w:p><w:pPr><w:pStyle w:val="AfterTable"/></w:pPr></w:p>')
        return "".join(out), i

    def blocks(self, tokens, rels: _Rels) -> str:
        out: list[str] = []
        i, n = 0, len(tokens)
        while i < n:
            t = tokens[i]
            typ = t.type
            if typ == "heading_open":
                out.append(self._heading(t, tokens[i + 1], rels))
                i += 3
                continue
            if typ == "paragraph_open":
                # A tight list's items are spaced like lines, not paragraphs.
                tight = '<w:spacing w:after="40"/>' if t.hidden else ""
                out.append(self._para(tokens[i + 1].children, rels, extra=tight))
                i += 3
                continue
            if typ in ("bullet_list_open", "ordered_list_open"):
                task = "contains-task-list" in str(t.attrs.get("class", ""))
                num = None
                if not task:
                    start = int(t.attrs.get("start", 1) or 1)
                    self.nums.append((1 if typ == "ordered_list_open" else 0, start))
                    num = len(self.nums)
                self.lists.append({"num": num, "pending": False, "task": task})
            elif typ in ("bullet_list_close", "ordered_list_close"):
                self.lists.pop()
            elif typ == "list_item_open":
                self.lists[-1]["pending"] = True
            elif typ == "blockquote_open":
                self.quote += 1
            elif typ == "blockquote_close":
                self.quote -= 1
            elif typ == "fence" and "chart" in t.meta:
                out.append(self._chart(t.meta["chart"], rels))
            elif typ in ("fence", "code_block"):
                out.append(self._code(t.content))
            elif typ == "hr":
                out.append(f"<w:p>{self._ppr('Rule')}</w:p>")
            elif typ == "table_open":
                xml, i = self._table(tokens, i, rels)
                out.append(xml)
            elif typ == "footnote_block_open":
                i = self._collect_footnotes(tokens, i)
            elif typ in ("html_block",):
                out.append(
                    f"<w:p>{self._ppr(None)}{self._run(t.content.rstrip())}</w:p>"
                )
            i += 1
        return "".join(out)

    # -- footnotes ----------------------------------------------------------

    def _collect_footnotes(self, tokens, i) -> int:
        current = None
        while tokens[i].type != "footnote_block_close":
            t = tokens[i]
            if t.type == "footnote_open":
                current = int(t.meta["id"])
                self._fn_tokens[current] = []
            elif t.type == "footnote_close":
                current = None
            elif current is not None:
                self._fn_tokens[current].append(t)
            i += 1
        return i

    def footnotes_xml(self, rels: _Rels) -> str:
        notes = []
        saved = (self.lists, self.quote, self.break_next)
        for fid in sorted(self._fn_tokens):
            self.lists, self.quote, self.break_next = [], 0, False
            self.in_footnote, self._fn_first = fid, True
            body = self.blocks(self._fn_tokens[fid], rels)
            if self._fn_first:  # an empty footnote still needs its number
                body = self._para([], rels) + body
            notes.append(f'<w:footnote w:id="{fid + 1}">{body}</w:footnote>')
        self.in_footnote = None
        self.lists, self.quote, self.break_next = saved
        return (
            XML_DECL + f"<w:footnotes {NS}>"
            '<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr>'
            '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
            "<w:r><w:separator/></w:r></w:p></w:footnote>"
            '<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr>'
            '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>'
            "<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>"
            + "".join(notes)
            + "</w:footnotes>"
        )

    # -- cover and contents -------------------------------------------------

    def front(self, rels: _Rels, toc_on: bool) -> str:
        doc, out = self.doc, []
        cover = [("Title", doc.title)]
        if doc.meta.get("subtitle"):
            cover.append(("Subtitle", doc.meta["subtitle"]))
        byline = " · ".join(
            str(doc.meta[k]) for k in ("author", "date") if doc.meta.get(k)
        )
        if byline:
            cover.append(("Byline", byline))
        rule = (
            f'<w:pBdr><w:bottom w:val="single" w:sz="18" w:space="8"'
            f' w:color="{self.theme.accent}"/></w:pBdr>'
        )
        for k, (style, text) in enumerate(cover):
            last = k == len(cover) - 1
            ppr = f'<w:pPr><w:pStyle w:val="{style}"/>{rule if last else ""}</w:pPr>'
            out.append(f"<w:p>{ppr}{self._run(text)}</w:p>")
        entries = (
            [h for h in doc.headings if h.level <= 2 and h.text != doc.title]
            if toc_on
            else []
        )
        if entries:
            out.append(
                '<w:p><w:pPr><w:pStyle w:val="ContentsHeading"/></w:pPr>'
                f"{self._run('Contents')}</w:p>"
            )
            for h in entries:
                name = self.bookmarks.get(h.anchor)
                run = self._run(h.text)
                if name:
                    run = f'<w:hyperlink w:anchor="{attr(name)}" w:history="1">{run}</w:hyperlink>'
                out.append(
                    f'<w:p><w:pPr><w:pStyle w:val="TOC{min(h.level, 2)}"/></w:pPr>'
                    f"{run}</w:p>"
                )
            # The contents get a page to themselves, as in the PDF. A leading
            # part (H1) already starts a page, so only break before anything else.
            first = next(iter(doc.tokens), None)
            if not (first and first.type == "heading_open" and first.tag == "h1"):
                self.break_next = True
        return "".join(out)


# --- package parts ---------------------------------------------------------


def _styles(th: WordTheme) -> str:
    body, head, mono = (attr(f) for f in (th.body, th.heading, th.mono))

    def fonts(f):
        return f'<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}" w:eastAsia="{f}"/>'

    def pstyle(sid, name, ppr="", rpr="", based="Normal", nxt="Normal", extra=""):
        return (
            f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
            f'<w:basedOn w:val="{based}"/><w:next w:val="{nxt}"/>{extra}<w:qFormat/>'
            f"<w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>"
        )

    def heading(level, size, before, after, extra_ppr=""):
        return pstyle(
            f"Heading{level}",
            f"heading {level}",
            "<w:keepNext/><w:keepLines/>"
            + extra_ppr
            + f'<w:spacing w:before="{before}" w:after="{after}" w:line="264"'
            ' w:lineRule="auto"/>'
            f'<w:outlineLvl w:val="{level - 1}"/>',
            f'{fonts(head)}<w:b/><w:bCs/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/>',
        )

    h2_rule = (
        f'<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="3" w:color="{th.rule}"/>'
        "</w:pBdr>"
    )
    code_shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{th.code_bg}"/>'
    styles = [
        (
            f"<w:docDefaults><w:rPrDefault><w:rPr>{fonts(body)}"
            '<w:color w:val="000000"/><w:sz w:val="21"/><w:szCs w:val="21"/>'
            '<w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="348"'
            ' w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        ),
        (
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/><w:qFormat/><w:pPr><w:widowControl/></w:pPr></w:style>'
        ),
        (
            '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont">'
            '<w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/>'
            "<w:semiHidden/><w:unhideWhenUsed/></w:style>"
        ),
        pstyle(
            "Title",
            "Title",
            '<w:keepNext/><w:spacing w:before="0" w:after="120" w:line="240"'
            ' w:lineRule="auto"/>',
            f'{fonts(head)}<w:b/><w:bCs/><w:sz w:val="52"/><w:szCs w:val="52"/>',
        ),
        pstyle(
            "Subtitle",
            "Subtitle",
            '<w:keepNext/><w:spacing w:after="80"/>',
            '<w:sz w:val="26"/><w:szCs w:val="26"/>',
        ),
        pstyle("Byline", "Byline", '<w:spacing w:after="80"/>', '<w:sz w:val="19"/>'),
        heading(1, 40, 0, 200, "<w:pageBreakBefore/>"),
        heading(2, 30, 400, 140, h2_rule if th.accent == "38BDF8" else ""),
        heading(3, 24, 280, 100),
        heading(4, 21, 240, 80),
        heading(5, 21, 240, 80),
        heading(6, 21, 240, 80),
        pstyle(
            "Quote",
            "Quote",
            f'<w:pBdr><w:left w:val="single" w:sz="24" w:space="10"'
            f' w:color="{th.accent}"/></w:pBdr><w:ind w:left="{LIST_INDENT}"/>',
        ),
        pstyle(
            "Code",
            "Code",
            f"<w:keepLines/>{code_shd}"
            '<w:spacing w:before="0" w:after="200" w:line="278" w:lineRule="exact"/>'
            '<w:ind w:left="115" w:right="115"/>',
            f'{fonts(mono)}<w:noProof/><w:sz w:val="17"/><w:szCs w:val="17"/>',
        ),
        pstyle(
            "TableText",
            "Table Text",
            '<w:spacing w:before="0" w:after="0" w:line="264" w:lineRule="auto"/>',
            '<w:sz w:val="18"/><w:szCs w:val="18"/>',
        ),
        pstyle(
            "AfterTable",
            "After Table",
            '<w:spacing w:before="0" w:after="120" w:line="120" w:lineRule="exact"/>',
            '<w:sz w:val="4"/>',
        ),
        pstyle(
            "Rule",
            "Horizontal Rule",
            f'<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1"'
            f' w:color="{th.rule}"/></w:pBdr><w:spacing w:before="120" w:after="240"'
            ' w:line="120" w:lineRule="exact"/>',
            '<w:sz w:val="4"/>',
        ),
        pstyle(
            "ContentsHeading",
            "Contents Heading",
            '<w:keepNext/><w:spacing w:before="480" w:after="160"/>',
            f'{fonts(head)}<w:b/><w:bCs/><w:sz w:val="30"/><w:szCs w:val="30"/>',
        ),
        pstyle(
            "TOC1",
            "toc 1",
            '<w:spacing w:before="80" w:after="20" w:line="264" w:lineRule="auto"/>',
            '<w:b/><w:sz w:val="19"/>',
        ),
        pstyle(
            "TOC2",
            "toc 2",
            '<w:spacing w:before="0" w:after="20" w:line="264" w:lineRule="auto"/>'
            f'<w:ind w:left="{LIST_INDENT}"/>',
            '<w:sz w:val="19"/>',
        ),
        pstyle(
            "FootnoteText",
            "footnote text",
            '<w:spacing w:after="60" w:line="240" w:lineRule="auto"/>',
            '<w:sz w:val="17"/><w:szCs w:val="17"/>',
        ),
        pstyle(
            "Footer",
            "footer",
            f'<w:tabs><w:tab w:val="right" w:pos="{TEXT_W}"/></w:tabs>'
            '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>',
            '<w:sz w:val="17"/><w:szCs w:val="17"/>',
        ),
        (
            '<w:style w:type="character" w:styleId="CodeChar"><w:name w:val="Inline Code"/>'
            f'<w:basedOn w:val="DefaultParagraphFont"/><w:rPr>{fonts(mono)}<w:noProof/>'
            f'<w:sz w:val="18"/><w:szCs w:val="18"/>{code_shd}</w:rPr></w:style>'
        ),
        (
            '<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>'
            '<w:basedOn w:val="DefaultParagraphFont"/><w:unhideWhenUsed/><w:rPr>'
            '<w:color w:val="000000"/><w:u w:val="single"/></w:rPr></w:style>'
        ),
        (
            '<w:style w:type="character" w:styleId="FootnoteReference">'
            '<w:name w:val="footnote reference"/><w:basedOn w:val="DefaultParagraphFont"/>'
            '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
        ),
    ]
    return XML_DECL + f"<w:styles {NS}>{''.join(styles)}</w:styles>"


def _numbering(nums: list[tuple[int, int]]) -> str:
    bullets = ("•", "◦", "▪")
    formats = (("decimal", "%{}."), ("lowerLetter", "%{}."), ("lowerRoman", "%{}."))

    def levels(ordered: bool) -> str:
        out = []
        for lvl in range(9):
            left = (lvl + 1) * LIST_INDENT
            if ordered:
                fmt, text = formats[lvl % 3]
                text = text.format(lvl + 1)
            else:
                fmt, text = "bullet", bullets[lvl % 3]
            out.append(
                f'<w:lvl w:ilvl="{lvl}"><w:start w:val="1"/>'
                f'<w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                '<w:lvlJc w:val="left"/><w:pPr>'
                f'<w:ind w:left="{left}" w:hanging="{LIST_INDENT}"/></w:pPr></w:lvl>'
            )
        return "".join(out)

    abstracts = (
        '<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/>'
        f"{levels(False)}</w:abstractNum>"
        '<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="multilevel"/>'
        f"{levels(True)}</w:abstractNum>"
    )
    # Every list gets its own numbering instance, so each ordered list
    # restarts at its own start number.
    instances = "".join(
        f'<w:num w:numId="{i}"><w:abstractNumId w:val="{abstract}"/>'
        + "".join(
            f'<w:lvlOverride w:ilvl="{lvl}"><w:startOverride w:val="{start}"/>'
            "</w:lvlOverride>"
            for lvl in range(9)
        )
        + "</w:num>"
        for i, (abstract, start) in enumerate(nums, 1)
    )
    return XML_DECL + f"<w:numbering {NS}>{abstracts}{instances}</w:numbering>"


def _footer(title: str | None) -> str:
    def field(code: str) -> str:
        return f'<w:fldSimple w:instr=" {code} "><w:r><w:t>1</w:t></w:r></w:fldSimple>'

    lead = f"{_Writer._run(title)}" if title else ""
    return (
        XML_DECL + f'<w:ftr {NS}><w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
        f"{lead}<w:r><w:tab/></w:r>{field('PAGE')}"
        f'<w:r><w:t xml:space="preserve"> / </w:t></w:r>{field("NUMPAGES")}'
        "</w:p></w:ftr>"
    )


def _font_table(th: WordTheme) -> str:
    rows = []
    for name in dict.fromkeys((th.body, th.heading, th.mono)):
        alt, family, pitch = FONT_FALLBACK.get(name, ("Arial", "swiss", "variable"))
        rows.append(
            f'<w:font w:name="{attr(name)}"><w:altName w:val="{alt}"/>'
            f'<w:family w:val="{family}"/><w:pitch w:val="{pitch}"/></w:font>'
        )
    return XML_DECL + f"<w:fonts {NS}>{''.join(rows)}</w:fonts>"


SETTINGS = (
    XML_DECL + f"<w:settings {NS}>"
    '<w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/>'
    '<w:characterSpacingControl w:val="doNotCompress"/>'
    '<w:footnotePr><w:footnote w:id="-1"/><w:footnote w:id="0"/></w:footnotePr>'
    '<w:compat><w:compatSetting w:name="compatibilityMode"'
    ' w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
    "</w:settings>"
)


def _core(doc: Document, theme: str) -> str:
    author = doc.meta.get("author")
    return (
        XML_DECL + "<cp:coreProperties "
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{esc(doc.title)}</dc:title>"
        + (f"<dc:creator>{esc(str(author))}</dc:creator>" if author else "")
        + f"<cp:keywords>rupa-theme:{esc(theme)}</cp:keywords>"
        "</cp:coreProperties>"
    )


APP = (
    XML_DECL + "<Properties "
    'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    f"<Application>Rupa {esc(__version__)}</Application></Properties>"
)

ROOT_RELS = (
    XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
    'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/'
    '2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    "</Relationships>"
)

_WML = "application/vnd.openxmlformats-officedocument.wordprocessingml"


def _content_types(exts: set[str]) -> str:
    mime = {"png": "image/png", "jpeg": "image/jpeg", "gif": "image/gif"}
    defaults = "".join(
        f'<Default Extension="{e}" ContentType="{mime[e]}"/>' for e in sorted(exts)
    )
    over = {
        "/word/document.xml": f"{_WML}.document.main+xml",
        "/word/styles.xml": f"{_WML}.styles+xml",
        "/word/settings.xml": f"{_WML}.settings+xml",
        "/word/numbering.xml": f"{_WML}.numbering+xml",
        "/word/footnotes.xml": f"{_WML}.footnotes+xml",
        "/word/fontTable.xml": f"{_WML}.fontTable+xml",
        "/word/footer1.xml": f"{_WML}.footer+xml",
        "/word/footer2.xml": f"{_WML}.footer+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
    }
    overrides = "".join(
        f'<Override PartName="{p}" ContentType="{t}"/>' for p, t in over.items()
    )
    return (
        XML_DECL
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f"{defaults}{overrides}</Types>"
    )


def _zip(parts: list[tuple[str, bytes]]) -> bytes:
    """A zip with fixed timestamps and order, so the bytes are reproducible."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            # Images are compressed already; deflating them again costs time.
            info.compress_type = (
                zipfile.ZIP_STORED
                if name.startswith("word/media/")
                else zipfile.ZIP_DEFLATED
            )
            z.writestr(info, data, compresslevel=6)
    return buf.getvalue()


def to_docx(
    doc: Document,
    theme: str = "default",
    base_dir: str | Path | None = None,
    toc_on: bool | None = None,
) -> bytes:
    """Return the document as DOCX bytes.

    Relative image paths resolve against base_dir (default: the current
    directory), and only files inside it can be read.
    """
    if theme not in WORD_THEMES:
        from .document import clip

        raise RenderError(f"unknown theme '{clip(theme)}' (have: {', '.join(THEMES)})")
    th = WORD_THEMES[theme]
    base = Path(base_dir or ".").resolve()
    if toc_on is None:
        toc_on = doc.meta.get("toc", True)

    writer = _Writer(doc, th, base, theme)
    doc_rels = _Rels(
        [
            (f"{REL}/styles", "styles.xml"),
            (f"{REL}/settings", "settings.xml"),
            (f"{REL}/numbering", "numbering.xml"),
            (f"{REL}/footnotes", "footnotes.xml"),
            (f"{REL}/fontTable", "fontTable.xml"),
            (f"{REL}/footer", "footer1.xml"),  # rId6: first page
            (f"{REL}/footer", "footer2.xml"),  # rId7: every other page
        ]
    )
    fn_rels = _Rels()
    front = writer.front(doc_rels, toc_on)
    body = writer.blocks(doc.tokens, doc_rels)
    footnotes = writer.footnotes_xml(fn_rels)
    sect = (
        '<w:sectPr><w:footerReference w:type="first" r:id="rId6"/>'
        '<w:footerReference w:type="default" r:id="rId7"/>'
        f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
        f'<w:pgMar w:top="{MARGIN_TOP}" w:right="{MARGIN_SIDE}"'
        f' w:bottom="{MARGIN_BOTTOM}" w:left="{MARGIN_SIDE}" w:header="720"'
        ' w:footer="576" w:gutter="0"/><w:titlePg/></w:sectPr>'
    )
    document = (
        XML_DECL + f"<w:document {NS}><w:body>{front}{body}{sect}</w:body></w:document>"
    )
    exts = {Path(p).suffix[1:] for p in writer.media}
    parts = [
        ("[Content_Types].xml", _content_types(exts)),
        ("_rels/.rels", ROOT_RELS),
        ("docProps/core.xml", _core(doc, theme)),
        ("docProps/app.xml", APP),
        ("word/document.xml", document),
        ("word/_rels/document.xml.rels", doc_rels.xml()),
        ("word/styles.xml", _styles(th)),
        ("word/settings.xml", SETTINGS),
        ("word/numbering.xml", _numbering(writer.nums)),
        ("word/footnotes.xml", footnotes),
        ("word/fontTable.xml", _font_table(th)),
        ("word/footer1.xml", _footer(None)),
        ("word/footer2.xml", _footer(doc.title)),
    ]
    if fn_rels.items:
        parts.append(("word/_rels/footnotes.xml.rels", fn_rels.xml()))
    encoded = [(name, text.encode("utf-8")) for name, text in parts]
    encoded += [(f"word/{p}", data) for p, data in writer.media.items()]
    return _zip(encoded)
