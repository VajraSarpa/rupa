"""Vega-Lite charts: check a spec, fill in its local data, draw it offline.

A chart is a Vega-Lite JSON spec, the same JSON Altair writes with
chart.save("x.vl.json"). It reaches Rupa two ways:

- a fenced block tagged vega-lite in the Markdown, checked at parse time
  (a bad spec is bad input, exit 3);
- an image link to a .vl.json file next to the Markdown, checked when the
  page is rendered (like any image file: exit 4).

Nothing in a chart reaches outside the document:

1. Every `url` or `href` key is refused, except a data source's `url` naming
   a .csv, .tsv or .json file inside the input's folder. Rupa reads that file
   itself, with the image guard's rules, and puts its text into the spec.
2. vl-convert is called with allowed_base_urls=[] (no fetching at all).
3. The SVG it returns must hold no href and no url() other than an internal
   #reference; otherwise the render fails.

vl-convert holds the GIL while it draws, so a slow chart can't be timed out
without a subprocess, which Rupa never runs. Work is bounded by input size
instead: rows per dataset, generated sequences, spec size and chart count.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from urllib.parse import unquote

from .document import InputError, clip

MAX_SPEC_BYTES = 1_000_000
MAX_ROWS = 5000  # per dataset, inline or from a file
MAX_DATA_BYTES = 2_000_000  # per data file
MAX_CHARTS = 50  # per document
DATA_SUFFIXES = {".csv": "csv", ".tsv": "tsv", ".json": "json"}
CHART_SUFFIX = ".vl.json"

# Screen and print widths in CSS px. A chart that sets no width fills the
# text column; its height stays at the spec's (or Vega-Lite's default).
COLUMN_PX = 640
CHART_HEIGHT_PX = 240


class ChartError(ValueError):
    """A spec Rupa won't draw. Exit 3 in a Markdown block, 4 in a file."""


def _where(path: list) -> str:
    return "/".join(str(p) for p in path) or "spec"


def check_spec(spec: object) -> dict:
    """Refuse anything that could fetch, or make the chart unboundedly big.

    Returns the spec unchanged. Data `url`s are left for fill_data, which
    needs the input's folder; here they only have to look like a local file.
    """
    if not isinstance(spec, dict):
        raise ChartError("a Vega-Lite spec must be a JSON object")

    def walk(node, path, parent_key):
        if isinstance(node, dict):
            for key, value in node.items():
                here = [*path, key]
                if key == "href":
                    raise ChartError(f"'href' at {_where(here)}: charts can't link")
                if key == "url":
                    if parent_key != "data" or not isinstance(value, str):
                        raise ChartError(
                            f"'url' at {_where(here)}: charts can't load images"
                            " or other resources; only data can come from a"
                            " .csv, .tsv or .json file next to the Markdown"
                        )
                    _check_data_path(value, here)
                if key == "values" and isinstance(value, list):
                    _check_rows(len(value), here)
                if key == "values" and isinstance(value, str):
                    _check_rows(len(value.strip().splitlines()) - 1, here)
                if key == "datasets" and isinstance(value, dict):
                    for name, rows in value.items():
                        if isinstance(rows, list):
                            _check_rows(len(rows), [*here, name])
                if key == "sequence" and isinstance(value, dict):
                    _check_sequence(value, here)
                walk(value, here, key)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, [*path, i], parent_key)

    walk(spec, [], None)
    return spec


def _check_data_path(value: str, path: list) -> None:
    if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", value) or value.startswith(("/", "\\")):
        raise ChartError(
            f"data url '{clip(value)}' at {_where(path)} must be a relative path"
            " to a file next to the Markdown"
        )
    if Path(value).suffix.lower() not in DATA_SUFFIXES:
        raise ChartError(f"data file '{clip(value)}' must be .csv, .tsv or .json")


def _check_rows(n: int, path: list) -> None:
    if n > MAX_ROWS:
        raise ChartError(
            f"{n:,} data rows at {_where(path)}; a chart takes at most {MAX_ROWS:,}"
            " (aggregate first)"
        )


def _check_sequence(seq: dict, path: list) -> None:
    try:
        start, stop = float(seq.get("start", 0)), float(seq["stop"])
        step = float(seq.get("step", 1)) or 1
        n = abs((stop - start) / step)
    except (KeyError, TypeError, ValueError):
        raise ChartError(f"sequence at {_where(path)} needs numeric start and stop")
    _check_rows(int(n), path)


def parse_block(source: str) -> dict:
    """A ```vega-lite block's JSON as a checked spec (InputError: exit 3)."""
    if len(source.encode("utf-8")) > MAX_SPEC_BYTES:
        raise InputError("vega-lite block is over 1 MB; put the data in a file")
    try:
        spec = json.loads(source)
    except json.JSONDecodeError as exc:
        raise InputError(
            f"vega-lite block is not valid JSON: line {exc.lineno},"
            f" column {exc.colno}: {exc.msg}"
        ) from exc
    try:
        return check_spec(spec)
    except ChartError as exc:
        raise InputError(f"vega-lite block: {exc}") from exc


def alt_text(spec: dict) -> str:
    """What a reader without the image gets: description, else title."""
    for key in ("description", "title"):
        value = spec.get(key)
        if isinstance(value, dict):
            value = value.get("text")
        if isinstance(value, list):
            value = " ".join(map(str, value))
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Chart"


def _local_file(src: str, base: Path, what: str) -> Path:
    """A file inside base, not hidden: the same rule as render.load_image."""
    from .render import RenderError

    path = (base / unquote(src)).resolve()
    if not path.is_relative_to(base):
        raise RenderError(f"blocked or missing {what}: {path} is outside {base}")
    if any(part.startswith(".") for part in path.relative_to(base).parts):
        raise RenderError(f"blocked {what}: {path} is a hidden file")
    if not path.is_file():
        raise RenderError(f"blocked or missing {what}: {path}")
    return path


def load_chart_file(src: str, base_dir: str | Path) -> dict:
    """A .vl.json file the Markdown links as an image, checked."""
    from .render import RenderError

    base = Path(base_dir).resolve()
    path = _local_file(src, base, "chart")
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise RenderError(f"chart {path.name} is over 1 MB")
    try:
        return check_spec(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RenderError(f"chart {path.name} is not valid JSON: {exc}") from exc
    except ChartError as exc:
        raise RenderError(f"chart {path.name}: {exc}") from exc


def fill_data(spec: dict, base_dir: str | Path) -> dict:
    """A copy of spec with each local data file's text put inline."""
    from .render import RenderError

    base = Path(base_dir).resolve()
    spec = copy.deepcopy(spec)

    def walk(node):
        if isinstance(node, dict):
            data = node.get("data")
            if isinstance(data, dict) and isinstance(data.get("url"), str):
                node["data"] = _inline(data, base)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    def _inline(data: dict, base: Path) -> dict:
        path = _local_file(data["url"], base, "data file")
        if path.stat().st_size > MAX_DATA_BYTES:
            raise RenderError(f"data file {path.name} is over 2 MB; aggregate first")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RenderError(f"data file {path.name} is not UTF-8 text") from exc
        kind = DATA_SUFFIXES[path.suffix.lower()]
        fmt = dict(data.get("format") or {})
        fmt.setdefault("type", kind)
        if fmt["type"] == "json":
            try:
                rows = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RenderError(f"data file {path.name} is not valid JSON") from exc
            prop = fmt.get("property")
            for part in str(prop).split(".") if prop else []:
                rows = rows.get(part) if isinstance(rows, dict) else None
            n = len(rows) if isinstance(rows, list) else 1
        else:
            n = max(0, len(text.strip().splitlines()) - 1)
        try:
            _check_rows(n, [path.name])
        except ChartError as exc:
            raise RenderError(str(exc)) from exc
        out = {k: v for k, v in data.items() if k not in ("url", "format")}
        out.update(values=text, format=fmt)
        return out

    walk(spec)
    return spec


# --- drawing -----------------------------------------------------------------

LIGHT = {"ink": "#000000", "muted": "#000000", "grid": "#d9dee5", "domain": "#64748b"}
# cyan-dark's PDF text colours (render.THEME_TEXT_COLORS) and cyan's screen ink.
DARK = {"ink": "#e6edf6", "muted": "#9fb0c8", "grid": "#26344a", "domain": "#6b7d98"}

THEME_CHART = {  # (font, accent, palette on screen, palette in PDF)
    "default": ("Inter", "#0e7490", "light", "light"),
    "cyan": ("Hanken Grotesk", "#38bdf8", "dark", "light"),
    "cyan-dark": ("Hanken Grotesk", "#38bdf8", "dark", "dark"),
}


def chart_config(theme: str, target: str) -> dict:
    """The Vega-Lite config a theme gives every chart, for html, pdf or docx."""
    font, accent, screen, paper = THEME_CHART[theme]
    palette = {"html": screen, "pdf": paper}.get(target, "light")  # DOCX: paper
    if target == "html":
        # An SVG shown as an <img> can't use the page's fonts, so the browser
        # needs fallbacks; PDF and PNG draw with the bundled fonts.
        font = f'"{font}", Inter, "Helvetica Neue", Arial, sans-serif'

    c = DARK if palette == "dark" else LIGHT
    axis = {
        "labelColor": c["muted"],
        "titleColor": c["ink"],
        "gridColor": c["grid"],
        "domainColor": c["domain"],
        "tickColor": c["domain"],
        "labelFont": font,
        "titleFont": font,
        "labelFontSize": 11,
        "titleFontSize": 12,
    }
    legend = {
        "labelColor": c["muted"],
        "titleColor": c["ink"],
        "labelFont": font,
        "titleFont": font,
        "labelFontSize": 11,
        "titleFontSize": 12,
    }
    config = {
        "font": font,
        "background": None,
        "view": {"stroke": None},
        "axis": axis,
        "legend": legend,
        "header": {"labelColor": c["ink"], "titleColor": c["ink"]},
        "title": {
            "color": c["ink"],
            "subtitleColor": c["muted"],
            "font": font,
            "fontSize": 14,
        },
        "text": {"color": c["ink"]},
        "mark": {"color": accent},
    }
    if theme == "default" and target == "html":
        # The default theme follows the system's light or dark mode, which an
        # image can't, so its charts sit on their own white card.
        config["background"] = "#ffffff"
        config["padding"] = 12
    return config


def _sized(spec: dict) -> dict:
    """A single view with no width fills the text column."""
    composite = ("hconcat", "vconcat", "concat", "facet", "repeat")
    if "width" in spec or "autosize" in spec or any(k in spec for k in composite):
        return spec
    if (
        "facet" in spec.get("encoding", {})
        or "row" in spec.get("encoding", {})
        or "column" in spec.get("encoding", {})
    ):
        return spec
    sized = {**spec, "width": COLUMN_PX}
    sized["autosize"] = {"type": "fit-x", "contains": "padding"}
    # Shorter than Vega-Lite's 300 so a printed chart stays under the 3in
    # figure cap with less shrinking, and its labels stay legible.
    sized.setdefault("height", CHART_HEIGHT_PX)
    return sized


def _vl_version(spec: dict, available: list[str]) -> str | None:
    """The newest bundled Vega-Lite with the spec's major version (Altair 5
    writes v5 specs; vl-convert defaults to v6)."""
    m = re.search(r"/vega-lite/v(\d+)", str(spec.get("$schema", "")))
    if not m:
        return None
    same = [v for v in available if v.split(".")[0] == m.group(1)]
    return same[-1] if same else None


_vlc = None


def _converter():
    global _vlc
    if _vlc is None:
        from .render import FONT_DIR, RenderError

        try:
            import vl_convert
        except ImportError as exc:
            raise RenderError(
                "charts need the charts extra: uv tool install 'rupa[charts]'"
                " (or pip install vl-convert-python)"
            ) from exc
        vl_convert.register_font_directory(str(FONT_DIR))
        _vlc = vl_convert
    return _vlc


_SVG_URL = re.compile(r"url\(\s*['\"]?(?!#)", re.IGNORECASE)
_SVG_HREF = re.compile(r"\bhref\s*=", re.IGNORECASE)


def _draw(spec: dict, theme: str, target: str, base_dir, fmt: str):
    from .render import RenderError

    vlc = _converter()
    spec = _sized(fill_data(spec, base_dir))
    kw = {
        "config": chart_config(theme, target),
        "allowed_base_urls": [],
        "vl_version": _vl_version(spec, vlc.get_vegalite_versions()),
    }
    try:
        if fmt == "svg":
            out = vlc.vegalite_to_svg(spec, **kw)
        else:
            out = vlc.vegalite_to_png(spec, scale=2, **kw)
    except Exception as exc:  # vl-convert raises ValueError with a JS trace
        lines = [ln for ln in str(exc).splitlines() if ln.strip()]
        detail = next(
            (ln for ln in lines if ln.startswith("Error")), lines[-1:] or [""]
        )
        raise RenderError(f"chart could not be drawn: {clip(detail)}") from exc
    if fmt == "svg" and (_SVG_URL.search(out) or _SVG_HREF.search(out)):
        raise RenderError("chart refused: its SVG links to an outside resource")
    return out


def to_svg(spec: dict, theme: str, target: str, base_dir) -> bytes:
    return _draw(spec, theme, target, base_dir, "svg").encode("utf-8")


def to_png(spec: dict, theme: str, base_dir) -> tuple[bytes, float, float]:
    """(PNG at 2x, width px, height px at 1x) for DOCX."""
    import io

    from PIL import Image

    # A PNG holds no links, and check_spec has already refused every url and
    # href, so only the SVG path needs the output check.
    png = _draw(spec, theme, "docx", base_dir, "png")
    with Image.open(io.BytesIO(png)) as img:
        return png, img.width / 2, img.height / 2
