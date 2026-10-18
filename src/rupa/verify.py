"""Verify a rendered PDF against a wants file.

Two tiers:
  1. Deterministic checks, run here in code: color, size, page count, empty
     pages, stranded headings, overflow. Free and repeatable.
  2. Evidence for a vision review: a side-by-side sheet (reference page |
     rendered page) for every flagged page, and with sample: per-type one
     per page type too. Rupa never calls
     a model; Claude reads the sheets and judges them against the rubric.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from .document import clip, yaml_problem

PT_PER_IN = 72
PAGE_SIZES = {"letter": (612, 792), "a4": (595, 842)}
# Body box from print.css (@page margins). Footer sits below BODY_BOTTOM.
MARGIN_TOP, MARGIN_SIDE, MARGIN_BOTTOM = 0.85, 0.8, 0.9
FOOTER_CUTOFF = 0.8  # inches from the bottom edge; lines below are footer
PART_HEADING_PT = 18  # an H1 "part" title is at least this size
HEADING_PT = 11.5  # bold, non-mono text at least this size is a heading

ALL_CHECKS = (
    "text-color",
    "page-size",
    "max-pages",
    "blank-page",
    "near-empty",
    "sparse",
    "heading-at-bottom",
    "overflow",
)
DEFAULT_RUBRIC = [
    "hierarchy: titles, headings and body read in the same order and weight as the reference",
    "spacing: margins, gaps and alignment match the reference; nothing crowded or floating",
    "overflow: no text, table or code is clipped, cut off or running into the margin",
    "page balance: no awkward breaks (a lone row, a stranded heading, a near-empty page)",
    "style: colors, rules and boxes match the reference; text is solid black",
]
SAMPLE_MODES = ("per-type", "flagged", "all", "none")
DEFAULT_WANTS = {
    "theme": "default",
    "page_size": "letter",
    "max_pages": 100,
    "text_color": None,  # None: the theme's colours (THEME_TEXT_COLORS in render.py)
    "sparse_fill": 0.4,
    "near_empty_fill": 0.2,
    "checks": list(ALL_CHECKS),
    "vision": {
        "sample": "flagged",
        "max_sheets": 8,
        "resolution": 90,
        "rubric": DEFAULT_RUBRIC,
    },
}
EXIT_CHECKS_FAILED = 5


class WantsError(ValueError):
    """Raised for an unreadable or invalid wants file."""


class PdfError(ValueError):
    """Raised when the file given to verify cannot be read as a PDF."""


# ---------------------------------------------------------------- wants


def load_wants(path: str | None) -> dict:
    wants = json.loads(json.dumps(DEFAULT_WANTS))  # deep copy
    if not path:
        return wants
    try:
        given = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise WantsError(f"cannot read wants file: {exc}") from exc
    except yaml.YAMLError as exc:
        raise WantsError(f"bad wants file: {yaml_problem(exc)}") from exc
    if not isinstance(given, dict):
        raise WantsError("wants file must be a YAML mapping")
    unknown = set(given) - set(DEFAULT_WANTS)
    if unknown:
        raise WantsError(f"unknown wants keys: {clip(sorted(map(str, unknown)))}")
    vision = given.pop("vision", {}) or {}
    if not isinstance(vision, dict):
        raise WantsError("vision must be a YAML mapping")
    unknown_v = set(vision) - set(DEFAULT_WANTS["vision"])
    if unknown_v:
        raise WantsError(f"unknown vision keys: {clip(sorted(map(str, unknown_v)))}")
    wants.update(given)
    wants["vision"].update(vision)
    _validate(wants)
    return wants


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_fraction(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (0 <= value <= 1)
    )


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _validate(wants: dict) -> None:
    """Reject bad values here, so verify() never fails halfway with a traceback."""
    from .render import THEMES

    vision = wants["vision"]
    # isinstance first: a list or mapping isn't hashable, so `in` would raise.
    if not isinstance(wants["theme"], str) or wants["theme"] not in THEMES:
        raise WantsError(f"theme must be one of {list(THEMES)}")
    if not isinstance(wants["page_size"], str) or wants["page_size"] not in PAGE_SIZES:
        raise WantsError(f"page_size must be one of {sorted(PAGE_SIZES)}")
    if not _is_int(wants["max_pages"]) or wants["max_pages"] < 1:
        raise WantsError("max_pages must be a whole number of at least 1")
    color = wants["text_color"]
    if color is not None and not (
        isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)
    ):
        raise WantsError(f"text_color must be #RRGGBB, got {color!r}")
    for key in ("sparse_fill", "near_empty_fill"):
        if not _is_fraction(wants[key]):
            raise WantsError(f"{key} must be a number from 0 to 1")
    if not _is_str_list(wants["checks"]):
        raise WantsError("checks must be a list of check names")
    bad = set(wants["checks"]) - set(ALL_CHECKS)
    if bad:
        raise WantsError(f"unknown checks: {sorted(bad)}")
    if not isinstance(vision["sample"], str) or vision["sample"] not in SAMPLE_MODES:
        raise WantsError(f"vision.sample must be one of {', '.join(SAMPLE_MODES)}")
    if not _is_int(vision["max_sheets"]) or vision["max_sheets"] < 0:
        raise WantsError("vision.max_sheets must be a whole number of at least 0")
    if not _is_int(vision["resolution"]) or not 30 <= vision["resolution"] <= 300:
        raise WantsError("vision.resolution must be a whole number from 30 to 300")
    if not _is_str_list(vision["rubric"]):
        raise WantsError("vision.rubric must be a list of strings")


# ---------------------------------------------------------------- page model


@dataclass
class Line:
    top: float
    bottom: float
    x0: float
    x1: float
    size: float
    mono: bool
    bold: bool
    text: str


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)  # body lines only, no footer
    colors: list[tuple] = field(
        default_factory=list
    )  # one entry per distinct color seen
    off_colors: int = 0  # number of chars not matching the wanted color
    content_bottom: float = 0.0
    table_frac: float = 0.0
    tables: list[tuple] = field(default_factory=list)  # (x0, top, x1, bottom)
    image_bottom: float = 0.0  # lowest image edge in the body; images have no text
    kind: str = "prose"

    @property
    def body_top(self) -> float:
        return MARGIN_TOP * PT_PER_IN

    @property
    def body_bottom(self) -> float:
        return self.height - MARGIN_BOTTOM * PT_PER_IN

    @property
    def fill(self) -> float:
        if not self.lines:
            return 0.0
        span = self.body_bottom - self.body_top
        if span <= 0:  # a page too small to have a body box
            return 0.0
        return max(0.0, min(1.0, (self.content_bottom - self.body_top) / span))

    @property
    def mono_frac(self) -> float:
        chars = sum(len(ln.text) for ln in self.lines) or 1
        return sum(len(ln.text) for ln in self.lines if ln.mono) / chars

    @property
    def starts_part(self) -> bool:
        # The first or second line: a theme may set a small label above a part title.
        return any(ln.size >= PART_HEADING_PT for ln in self.lines[:2])


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    v = value.lstrip("#")
    if len(v) != 6:
        raise WantsError(f"text_color must be #RRGGBB, got {value!r}")
    return tuple(int(v[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _to_rgb(color) -> tuple[float, float, float] | None:
    """Normalize a pdfplumber color (gray, RGB or CMYK tuple) to RGB."""
    if color is None:
        return None
    c = tuple(color) if isinstance(color, (list, tuple)) else (color,)
    if len(c) == 1:
        return (c[0], c[0], c[0])
    if len(c) == 3:
        return c
    if len(c) == 4:
        cy, m, y, k = c
        return ((1 - cy) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _same_color(a, b, tol: float = 0.01) -> bool:
    return a is not None and all(abs(x - y) <= tol for x, y in zip(a, b))


def _text_colors(value) -> tuple[str, ...]:
    """A wants text_color (one colour, several, or None) as a tuple of colours."""
    if value is None:
        return ("#000000",)
    return (value,) if isinstance(value, str) else tuple(value)


def read_pages(pdf_path: str | Path, wanted_color="#000000") -> list[PageInfo]:
    """wanted_color: one #RRGGBB or several; any other text colour counts as off."""
    import pdfplumber

    want = [_hex_to_rgb(c) for c in _text_colors(wanted_color)]
    try:
        return _read_pages(pdfplumber, pdf_path, want)
    except Exception as exc:  # pdfminer raises many types on a damaged file
        raise PdfError(f"cannot read PDF {pdf_path}: {exc}") from exc


def _read_pages(pdfplumber, pdf_path, want) -> list[PageInfo]:
    pages: list[PageInfo] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            info = PageInfo(
                number=i, width=float(page.width), height=float(page.height)
            )
            seen: set = set()
            for ch in page.chars:
                rgb = _to_rgb(ch.get("non_stroking_color"))
                seen.add(rgb)
                if not any(_same_color(rgb, w) for w in want):
                    info.off_colors += 1
            info.colors = sorted(c for c in seen if c is not None)
            footer_y = info.height - FOOTER_CUTOFF * PT_PER_IN
            for tl in page.extract_text_lines(return_chars=True):
                if tl["top"] >= footer_y or not tl["chars"]:
                    continue
                chars = tl["chars"]
                fonts = [c.get("fontname", "") for c in chars]
                info.lines.append(
                    Line(
                        top=tl["top"],
                        bottom=tl["bottom"],
                        x0=tl["x0"],
                        x1=tl["x1"],
                        size=max(c["size"] for c in chars),
                        mono=sum("Mono" in f for f in fonts) > len(fonts) / 2,
                        bold=sum(
                            any(w in f for w in ("Bold", "SemiBold", "Black"))
                            for f in fonts
                        )
                        > len(fonts) / 2,
                        text=tl["text"],
                    )
                )
            body_h = info.body_bottom - info.body_top
            # The page background is painted as one big white rect; ignore it and
            # anything else that spans nearly the whole body.
            rects = [
                r
                for r in page.rects
                if r["bottom"] < footer_y and r["height"] < 0.95 * body_h
            ]
            line_bottoms = [ln.bottom for ln in info.lines]
            info.image_bottom = max(
                (im["bottom"] for im in page.images if im["bottom"] < footer_y),
                default=0.0,
            )
            info.content_bottom = max(
                [r["bottom"] for r in rects] + line_bottoms + [info.image_bottom],
                default=0.0,
            )
            body_area = (info.width - 2 * MARGIN_SIDE * PT_PER_IN) * body_h
            big = 0.95 * body_h
            no_bg = page.filter(
                lambda o, big=big: (
                    not (o.get("object_type") == "rect" and o["height"] >= big)
                )
            )
            tables = [t for t in no_bg.find_tables() if len(t.columns) >= 2]
            info.tables = [t.bbox for t in tables]
            table_area = sum(
                (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]) for t in tables
            )
            info.table_frac = min(1.0, table_area / body_area) if body_area else 0.0
            info.kind = classify(info)
            pages.append(info)
    return pages


def classify(p: PageInfo) -> str:
    if p.number == 1:
        return "cover"
    if p.mono_frac > 0.5:
        return "code"
    if p.table_frac > 0.3:
        return "table"
    return "prose"


# ---------------------------------------------------------------- checks


@dataclass
class CheckResult:
    id: str
    ok: bool
    pages: list[int] = field(default_factory=list)
    detail: str = ""


def run_checks(pages: list[PageInfo], wants: dict) -> list[CheckResult]:
    enabled = wants["checks"]
    results: list[CheckResult] = []
    last = len(pages)

    def add(cid: str, bad: list[int], detail: str) -> None:
        if cid in enabled:
            results.append(CheckResult(cid, not bad, bad, detail if bad else ""))

    add(
        "text-color",
        [p.number for p in pages if p.off_colors],
        f"text not {' or '.join(_text_colors(wants['text_color']))}",
    )
    w, h = PAGE_SIZES[wants["page_size"]]
    add(
        "page-size",
        [p.number for p in pages if abs(p.width - w) > 1 or abs(p.height - h) > 1],
        f"page is not {wants['page_size']}",
    )
    add(
        "max-pages",
        list(range(wants["max_pages"] + 1, last + 1)),
        f"{last} pages > max {wants['max_pages']}",
    )
    add("blank-page", [p.number for p in pages if not p.lines], "page has no text")

    near_empty = [
        p.number
        for p in pages
        # The cover (page 1) ends in a forced break and the last page ends the
        # document, so neither is judged on how full it is.
        if p.lines and p.number not in (1, last) and p.fill < wants["near_empty_fill"]
    ]
    add("near-empty", near_empty, f"under {wants['near_empty_fill']:.0%} full")

    sparse = []
    for idx, p in enumerate(pages):
        if not p.lines or p.number in (1, last) or p.number in near_empty:
            continue
        next_starts_part = idx + 1 < last and pages[idx + 1].starts_part
        if p.fill < wants["sparse_fill"] and not next_starts_part:
            sparse.append(p.number)
    add(
        "sparse",
        sparse,
        f"under {wants['sparse_fill']:.0%} full with no part break after",
    )

    def is_heading(ln: Line) -> bool:
        return ln.bold and not ln.mono and ln.size >= HEADING_PT

    stranded = []
    # The last page is exempt: nothing follows its final line, so no page break
    # separated a heading from its content (this also covers a title-only doc).
    for idx, p in enumerate(pages[:-1]):
        if not p.lines or p.image_bottom > p.lines[-1].bottom:
            continue  # an image after the last line is the heading's content
        if is_heading(p.lines[-1]):
            stranded.append(p.number)
            continue
        # A heading and a one-line lead-in ("Run this:") whose block moved to
        # the next page. A complete one-line section before a new heading is fine.
        nxt = pages[idx + 1].lines
        if (
            len(p.lines) >= 2
            and is_heading(head := p.lines[-2])
            and p.lines[-1].top - head.bottom < 2 * head.size  # directly under it
            and nxt
            and not is_heading(nxt[0])
        ):
            stranded.append(p.number)
    add(
        "heading-at-bottom",
        stranded,
        "heading is the last line, or a heading and one line end the page",
    )

    overflow, where = [], []
    for p in pages:
        left = MARGIN_SIDE * PT_PER_IN - 2
        right = p.width - MARGIN_SIDE * PT_PER_IN + 2
        bad = [ln for ln in p.lines if ln.x0 < left or ln.x1 > right]
        if bad:
            overflow.append(p.number)
            over = max(max(left - ln.x0, ln.x1 - right) for ln in bad) + 2
            where.append(f"p{p.number} {_overflow_kind(p, bad)} by {over:.0f}pt")
    add(
        "overflow",
        overflow,
        f"text extends past the side margins ({', '.join(where)})",
    )
    return results


def _overflow_kind(p: PageInfo, bad: list[Line]) -> str:
    """Name what runs over, so the fix is clear: a table, code, or text."""

    def in_table(ln: Line) -> bool:
        mid = (ln.top + ln.bottom) / 2
        return any(top <= mid <= bottom for _, top, _, bottom in p.tables)

    if any(in_table(ln) for ln in bad):
        return "table"
    return "code" if any(ln.mono for ln in bad) else "text"


# ---------------------------------------------------------------- sampling + sheets


def sample_pages(
    pages: list[PageInfo], results: list[CheckResult], wants: dict
) -> list[PageInfo]:
    """Flagged pages first, then one representative (the middle one) per page kind.

    "flagged" stops after the flagged pages, so a clean PDF gets no sheets.
    """
    mode = wants["vision"]["sample"]
    if mode == "none":
        return []
    if mode == "all":
        return pages[: wants["vision"]["max_sheets"]]
    flagged = sorted({n for r in results for n in r.pages if n <= len(pages)})
    chosen: list[int] = list(flagged)
    for kind in () if mode == "flagged" else ("cover", "prose", "table", "code"):
        of_kind = [p.number for p in pages if p.kind == kind]
        if of_kind and not any(n in of_kind for n in chosen):
            chosen.append(of_kind[len(of_kind) // 2])
    by_number = {p.number: p for p in pages}
    return [by_number[n] for n in chosen[: wants["vision"]["max_sheets"]]]


def reference_path(theme: str, kind: str):
    ref = resources.files("rupa") / "references" / theme / f"{kind}.png"
    return ref if ref.is_file() else None


def _label(img, text: str):
    from PIL import Image, ImageDraw, ImageFont

    strip = 28
    out = Image.new("RGB", (img.width, img.height + strip), "white")
    out.paste(img, (0, strip))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    draw.text((8, 5), text, fill="black", font=font)
    return out


# A sheet's rendered page is at most this many pixels on its long side, so an
# oversized page can't exhaust memory. Letter at 300 dpi is 3300.
MAX_SHEET_PX = 3300


def render_page_png(pdf_path: str | Path, number: int, resolution: int):
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[number - 1]
        long_side = max(float(page.width), float(page.height))
        if min(float(page.width), float(page.height)) <= 0:
            raise PdfError(f"page {number} has no size ({page.width}x{page.height}pt)")
        resolution = min(resolution, MAX_SHEET_PX * PT_PER_IN / long_side)
        return page.to_image(resolution=resolution).original.convert("RGB")


def make_sheet(
    pdf_path, page: PageInfo, flags: list[str], theme: str, resolution: int, out: Path
) -> Path:
    from PIL import Image

    rendered = render_page_png(pdf_path, page.number, resolution)
    right = _label(
        rendered,
        f"PAGE {page.number} ({page.kind})"
        + (f"  FLAGGED: {', '.join(flags)}" if flags else ""),
    )
    ref = reference_path(theme, page.kind)
    if ref is None:
        sheet = right
    else:
        with resources.as_file(ref) as ref_file:
            ref_img = Image.open(ref_file).convert("RGB")
            ref_img = ref_img.resize(
                (
                    round(ref_img.width * rendered.height / ref_img.height),
                    rendered.height,
                )
            )
        left = _label(ref_img, f"REFERENCE: {page.kind} ({theme})")
        sheet = Image.new(
            "RGB", (left.width + right.width + 16, right.height), (148, 163, 184)
        )
        sheet.paste(left, (0, 0))
        sheet.paste(right, (left.width + 16, 0))
    path = out / f"sheet-p{page.number:03d}-{page.kind}.png"
    sheet.save(path, optimize=True)
    return path


# ---------------------------------------------------------------- entry point


@dataclass
class VerifyReport:
    pdf: str
    pages: int
    checks: list[CheckResult]
    sheets: list[dict]
    rubric: list[str]
    manifest: str = ""

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def summary(self) -> str:
        passed = sum(c.ok for c in self.checks)
        fails = [
            f"{c.id} p{','.join(map(str, c.pages[:6]))}"
            for c in self.checks
            if not c.ok
        ]
        line = f"verify: {passed}/{len(self.checks)} checks pass"
        if fails:
            line += f" (FAIL {'; '.join(fails)})"
        if self.sheets:
            n = len(self.sheets)
            line += (
                f"; {n} sheet{'s' if n != 1 else ''} for visual review"
                f" in {Path(self.manifest).parent}/"
            )
        return line


def pdf_theme(pdf_path: str | Path) -> str | None:
    """The theme Rupa rendered this PDF with (its keywords metadata), if known."""
    import pdfplumber

    from .render import THEMES

    try:
        with pdfplumber.open(pdf_path) as pdf:
            keywords = str(pdf.metadata.get("Keywords", ""))
    except Exception:  # noqa: BLE001 - an unreadable PDF is reported by read_pages
        return None
    m = re.search(r"rupa-theme:([\w-]+)", keywords)
    return m.group(1) if m and m.group(1) in THEMES else None


def _clear_old_sheets(out: Path) -> None:
    """Remove the sheets the last verify listed in out/verify.json.

    Only those: --out may name a folder that holds other files, even ones
    named like sheets.
    """
    try:
        listed = json.loads((out / "verify.json").read_text())["sheets"]
        names = {Path(s["path"]).name for s in listed}
    except (OSError, ValueError, TypeError, KeyError):
        return
    for name in names:
        if re.fullmatch(r"sheet-p\d+-\w+\.png", name):
            (out / name).unlink(missing_ok=True)


def verify(
    pdf_path: str | Path, wants: dict, out_dir: str | Path, theme: str | None = None
) -> VerifyReport:
    from .render import THEME_TEXT_COLORS

    # --theme, else the theme Rupa recorded in the PDF, else the wants file's.
    theme = theme or pdf_theme(pdf_path) or wants["theme"]
    if not wants["text_color"]:
        wants = {**wants, "text_color": THEME_TEXT_COLORS[theme]}
    out = Path(out_dir)
    pages = read_pages(pdf_path, wants["text_color"])
    if not pages:  # every check loops over pages, so none would all "pass"
        raise PdfError(f"{pdf_path} has no pages")
    results = run_checks(pages, wants)
    out.mkdir(parents=True, exist_ok=True)
    _clear_old_sheets(out)
    flags_by_page: dict[int, list[str]] = {}
    for r in results:
        for n in r.pages:
            flags_by_page.setdefault(n, []).append(r.id)
    sheets = []
    for p in sample_pages(pages, results, wants):
        flags = flags_by_page.get(p.number, [])
        try:
            path = make_sheet(
                pdf_path, p, flags, theme, wants["vision"]["resolution"], out
            )
        except PdfError:
            raise
        except Exception as exc:  # pdfium and Pillow raise many types
            raise PdfError(f"cannot make the sheet for page {p.number}: {exc}") from exc
        sheets.append(
            {"path": str(path), "page": p.number, "kind": p.kind, "flags": flags}
        )
    report = VerifyReport(
        pdf=str(pdf_path),
        pages=len(pages),
        checks=results,
        sheets=sheets,
        rubric=wants["vision"]["rubric"],
        manifest=str(out / "verify.json"),
    )
    Path(report.manifest).write_text(
        json.dumps(
            {
                "pdf": report.pdf,
                "pages": report.pages,
                "ok": report.ok,
                "checks": [asdict(c) for c in results],
                "sheets": sheets,
                "rubric": report.rubric,
            },
            indent=2,
        )
    )
    return report


# ---------------------------------------------------------------- references


def build_references(
    pdf_path: str | Path, out_dir: str | Path, resolution: int = 90
) -> dict[str, int]:
    """Save the most typical page of each kind in a sample render as <kind>.png.

    Raises ValueError if the sample is missing a page kind, or if a picked page
    spills onto the next page, since a reference must show one whole page.
    """
    pages = read_pages(pdf_path)
    best: dict[str, PageInfo] = {}
    score = {
        "cover": lambda p: 1,
        "code": lambda p: p.mono_frac * p.fill,
        "table": lambda p: p.table_frac * p.fill,
        "prose": lambda p: p.fill,
    }
    for p in pages:
        if p.kind not in best or score[p.kind](p) > score[p.kind](best[p.kind]):
            best[p.kind] = p
    missing = {"cover", "prose", "table", "code"} - set(best)
    if missing:
        raise ValueError(f"sample has no {sorted(missing)} page; extend it")
    for kind, p in best.items():
        nxt = p.number  # pages are 1-based, so this indexes the following page
        if kind != "cover" and nxt < len(pages) and pages[nxt].kind == kind:
            raise ValueError(f"sample {kind} page p{p.number} spills over; trim it")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for kind, p in best.items():
        render_page_png(pdf_path, p.number, resolution).save(
            out / f"{kind}.png", optimize=True
        )
    return {kind: p.number for kind, p in best.items()}
