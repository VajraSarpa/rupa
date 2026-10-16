"""Verify a rendered PDF against a wants file.

Two tiers:
  1. Deterministic checks, run here in code: color, size, page count, empty
     pages, stranded headings, overflow. Free and repeatable.
  2. Evidence for a vision review: one side-by-side sheet per page type
     (reference page | rendered page) plus every flagged page. Rupa never calls
     a model; Claude reads the sheets and judges them against the rubric.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

import yaml

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
DEFAULT_WANTS = {
    "theme": "default",
    "page_size": "letter",
    "max_pages": 100,
    "text_color": "#000000",
    "sparse_fill": 0.4,
    "near_empty_fill": 0.2,
    "checks": list(ALL_CHECKS),
    "vision": {
        "sample": "per-type",
        "max_sheets": 8,
        "resolution": 90,
        "rubric": DEFAULT_RUBRIC,
    },
}
EXIT_CHECKS_FAILED = 5


class WantsError(ValueError):
    """Raised for an unreadable or invalid wants file."""


# ---------------------------------------------------------------- wants


def load_wants(path: str | None) -> dict:
    wants = json.loads(json.dumps(DEFAULT_WANTS))  # deep copy
    if not path:
        return wants
    try:
        given = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise WantsError(f"cannot read wants file: {exc}") from exc
    if not isinstance(given, dict):
        raise WantsError("wants file must be a YAML mapping")
    unknown = set(given) - set(DEFAULT_WANTS)
    if unknown:
        raise WantsError(f"unknown wants keys: {sorted(unknown)}")
    vision = given.pop("vision", {}) or {}
    unknown_v = set(vision) - set(DEFAULT_WANTS["vision"])
    if unknown_v:
        raise WantsError(f"unknown vision keys: {sorted(unknown_v)}")
    wants.update(given)
    wants["vision"].update(vision)
    bad = set(wants["checks"]) - set(ALL_CHECKS)
    if bad:
        raise WantsError(f"unknown checks: {sorted(bad)}")
    if wants["page_size"] not in PAGE_SIZES:
        raise WantsError(f"page_size must be one of {sorted(PAGE_SIZES)}")
    if wants["vision"]["sample"] not in ("per-type", "all", "none"):
        raise WantsError("vision.sample must be per-type, all or none")
    return wants


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
        return max(0.0, min(1.0, (self.content_bottom - self.body_top) / span))

    @property
    def mono_frac(self) -> float:
        chars = sum(len(ln.text) for ln in self.lines) or 1
        return sum(len(ln.text) for ln in self.lines if ln.mono) / chars

    @property
    def starts_part(self) -> bool:
        return bool(self.lines) and self.lines[0].size >= PART_HEADING_PT


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


def read_pages(pdf_path: str | Path, wanted_color: str = "#000000") -> list[PageInfo]:
    import pdfplumber

    want = _hex_to_rgb(wanted_color)
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
                if not _same_color(rgb, want):
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
            info.content_bottom = max(
                [r["bottom"] for r in rects] + line_bottoms, default=0.0
            )
            body_area = (info.width - 2 * MARGIN_SIDE * PT_PER_IN) * body_h
            big = 0.95 * body_h
            no_bg = page.filter(
                lambda o, big=big: (
                    not (o.get("object_type") == "rect" and o["height"] >= big)
                )
            )
            tables = [t for t in no_bg.find_tables() if len(t.columns) >= 2]
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
        f"text not {wants['text_color']}",
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

    stranded = []
    # The last page is exempt: nothing follows its final line, so no page break
    # separated a heading from its content (this also covers a title-only doc).
    for p in pages[:-1]:
        if p.lines:
            tail = p.lines[-1]
            if tail.bold and not tail.mono and tail.size >= HEADING_PT:
                stranded.append(p.number)
    add("heading-at-bottom", stranded, "heading is the last line on the page")

    overflow = []
    for p in pages:
        left = MARGIN_SIDE * PT_PER_IN - 2
        right = p.width - MARGIN_SIDE * PT_PER_IN + 2
        if any(ln.x0 < left or ln.x1 > right for ln in p.lines):
            overflow.append(p.number)
    add("overflow", overflow, "text extends past the side margins")
    return results


# ---------------------------------------------------------------- sampling + sheets


def sample_pages(
    pages: list[PageInfo], results: list[CheckResult], wants: dict
) -> list[PageInfo]:
    """Flagged pages first, then one representative (the middle one) per page kind."""
    mode = wants["vision"]["sample"]
    if mode == "none":
        return []
    if mode == "all":
        return pages[: wants["vision"]["max_sheets"]]
    flagged = sorted({n for r in results for n in r.pages if n <= len(pages)})
    chosen: list[int] = list(flagged)
    for kind in ("cover", "prose", "table", "code"):
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


def render_page_png(pdf_path: str | Path, number: int, resolution: int):
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return (
            pdf.pages[number - 1]
            .to_image(resolution=resolution)
            .original.convert("RGB")
        )


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


def verify(
    pdf_path: str | Path, wants: dict, out_dir: str | Path, theme: str | None = None
) -> VerifyReport:
    theme = theme or wants["theme"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("sheet-p*.png"):
        old.unlink()
    pages = read_pages(pdf_path, wants["text_color"])
    results = run_checks(pages, wants)
    flags_by_page: dict[int, list[str]] = {}
    for r in results:
        for n in r.pages:
            flags_by_page.setdefault(n, []).append(r.id)
    sheets = []
    for p in sample_pages(pages, results, wants):
        flags = flags_by_page.get(p.number, [])
        path = make_sheet(pdf_path, p, flags, theme, wants["vision"]["resolution"], out)
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
