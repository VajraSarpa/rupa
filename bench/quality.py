"""Check every arm's output the same way, without Rupa's own rules.

`rupa verify` holds a PDF to Rupa's house style (black text, its margins), so
it can't judge the baseline fairly. These checks ask only what the task asked
for and what any printed page needs:

- pages: the page count the task asked for (from the task's checks.json)
- in_bounds: no text or image outside the page box (images since v0.1.3)
- printable: no text within 12 pt (about 0.17 in) of the edge, where printers clip
- min_font: no text smaller than 6 pt
- phrases: each required phrase appears (case and spacing ignored)
- json: a JSON block of at least N lines parses (running headers removed)
- numbered: a numbered list runs 1..N

json and numbered pass when found and are unknown, not failed, when not: a
two-column layout or an odd list style defeats text extraction, and the judge
checks the same requirement from the page images.
- image: the PDF contains an image
- html_self_contained: an HTML file loads nothing over the network

Each check is pass, fail, or unknown (not asked for). `words` is reported, not
scored. What text extraction can't decide (is the table complete?) goes to the
judge's checklist instead (`judge` in checks.json).

Usage: uv run python bench/quality.py bench/results/<stamp>-<task> [...]
       writes quality.json in each folder and prints one line per output
"""

import json
import re
import subprocess
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pdfplumber

EDGE_PT = 12
PAGE_NUMBER = re.compile(r"(page )?#( ?(/|of) ?#)?", re.IGNORECASE)
MIN_FONT_PT = 6


def norm(text: str) -> str:
    text = text.replace("\xad", "").replace("-\n", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def pdf_lines(path: Path) -> list[str]:
    """Text lines in reading order, with running headers and footers removed.

    A header or footer is one of a page's first or last two lines that appears,
    digits aside, on at least two pages. Without this a page break inside a
    code block breaks the block.
    """
    text = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=False
    ).stdout
    pages = [[line for line in p.splitlines() if line.strip()] for p in text.split("\f")]
    key = lambda s: re.sub(r"\s+", " ", re.sub(r"\d+", "#", s.strip()))
    edges = lambda p: p[:2] + p[-2:]
    counts = Counter(k for p in pages for k in {key(line) for line in edges(p)})
    repeated = {k for k, n in counts.items() if n >= 2}
    repeated |= {k for p in pages for k in map(key, edges(p)) if PAGE_NUMBER.fullmatch(k)}
    out = []
    for p in pages:
        last = len(p) - 2
        out += [s for i, s in enumerate(p) if not ((i < 2 or i >= last) and key(s) in repeated)]
    return out


def json_blocks(lines: list[str]) -> list[tuple[bool, int]]:
    """Each block that starts with a line opening "{": (parses, line count)."""
    found, i = [], 0
    while i < len(lines):
        if not lines[i].strip().startswith("{"):
            i += 1
            continue
        depth, buf, j = 0, [], i
        for j in range(i, len(lines)):
            s = lines[j].strip()
            buf.append(s)
            depth += s.count("{") + s.count("[") - s.count("}") - s.count("]")
            if depth <= 0:
                break
        try:
            json.loads("\n".join(buf))
            found.append((True, len(buf)))
        except json.JSONDecodeError:
            found.append((False, len(buf)))
        i = j + 1
    return found


def numbered_run(lines: list[str]) -> int:
    """Longest numbered list: the largest N such that items 1..N all start a line."""
    starts = {int(m.group(1)) for s in lines if (m := re.match(r"\s*(\d+)(?:[.)]\s+|\s{2,})\S", s))}
    n = 0
    while n + 1 in starts:
        n += 1
    return n


def result(ok: bool | None, detail: object = "") -> dict:
    return {"ok": ok, "detail": str(detail)}


def check_phrases(text: str, phrases: list[str]) -> dict:
    missing = [p for p in phrases if norm(p) not in text]
    return result(not missing, f"missing {missing}" if missing else f"{len(phrases)} found")


def check_pdf(path: Path, spec: dict) -> dict:
    out = {}
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        chars = [(p, c) for p in pages for c in p.chars if c["text"].strip()]
        text = norm("\n".join(p.extract_text() or "" for p in pages))
        has_image = any(p.images for p in pages)
        if "pages" in spec:
            out["pages"] = result(len(pages) == spec["pages"], f"{len(pages)} of {spec['pages']}")
        outside = [c for p, c in chars if c["x0"] < -1 or c["x1"] > p.width + 1
                   or c["top"] < -1 or c["bottom"] > p.height + 1]
        images = [(p, im) for p in pages for im in p.images]
        off = [im for p, im in images if im["x0"] < -1 or im["x1"] > p.width + 1
               or im["top"] < -1 or im["bottom"] > p.height + 1]
        out["in_bounds"] = result(not outside and not off,
                                  f"{len(outside)} chars, {len(off)} images outside")
        edge = [c for p, c in chars if c["x0"] < EDGE_PT or c["x1"] > p.width - EDGE_PT
                or c["top"] < EDGE_PT or c["bottom"] > p.height - EDGE_PT]
        out["printable"] = result(not edge, f"{len(edge)} chars within {EDGE_PT} pt of an edge")
        smallest = min((round(c["size"], 1) for _, c in chars), default=0)
        out["min_font"] = result(bool(chars) and smallest >= MIN_FONT_PT, f"{smallest} pt")
    lines = pdf_lines(path)
    out["words"] = result(None, len(text.split()))
    if spec.get("phrases"):
        out["phrases"] = check_phrases(text, spec["phrases"])
    if "json_min_lines" in spec:
        best = max((n for ok, n in json_blocks(lines) if ok), default=0)
        out["json"] = result(best >= spec["json_min_lines"] or None,
                             f"longest parsing block {best} lines")
    if "numbered_min" in spec:
        n = numbered_run(lines)
        out["numbered"] = result(n >= spec["numbered_min"] or None, f"runs 1..{n}")
    if spec.get("image"):
        out["image"] = result(has_image, "image found" if has_image else "no image")
    return out


class _Html(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text, self.remote, self.images, self.ol_items, self._ol = [], [], 0, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for attr in ("src", "href"):
            url = a.get(attr) or ""
            loads = tag in ("img", "script", "iframe", "source") or (
                tag == "link" and "stylesheet" in (a.get("rel") or ""))
            if loads and re.match(r"(https?:)?//", url):
                self.remote.append(url)
        self.images += tag in ("img", "svg")
        self._ol += tag == "ol"
        self.ol_items += tag == "li" and self._ol > 0

    def handle_endtag(self, tag):
        self._ol -= tag == "ol" and self._ol > 0

    def handle_data(self, data):
        self.text.append(data)


def check_html(path: Path, spec: dict) -> dict:
    page = _Html()
    page.feed(path.read_text(errors="replace"))
    text = norm(" ".join(page.text))
    out = {"words": result(None, len(text.split()))}
    out["html_self_contained"] = result(not page.remote, f"remote: {page.remote[:3]}"
                                        if page.remote else "nothing remote")
    if spec.get("phrases"):
        out["phrases"] = check_phrases(text, spec["phrases"])
    if "numbered_min" in spec:
        out["numbered"] = result(page.ol_items >= spec["numbered_min"], f"{page.ol_items} items")
    if spec.get("image"):
        out["image"] = result(page.images > 0, f"{page.images} images")
    return out


def check(path: Path, spec: dict) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        return {"exists": result(False, "no output")}
    try:
        checks = check_pdf(path, spec) if path.suffix == ".pdf" else check_html(path, spec)
    except Exception as e:  # noqa: BLE001  an unreadable file is a failed output, not a crash
        return {"exists": result(True), "readable": result(False, f"{type(e).__name__}: {e}")}
    return {"exists": result(True), **checks}


def score(checks: dict) -> tuple[int, int]:
    decided = [c["ok"] for c in checks.values() if c["ok"] is not None]
    return sum(decided), len(decided)


def run_checks(results: Path, stem: str) -> dict:
    """Checks for one run of a bench v2 folder, e.g. stem "baseline-2".

    A session task's checks.json is {"steps": [spec, ...]}, one spec per output;
    its checks are keyed "s1.pages", "s2.pages", and so on.
    """
    manifest = json.loads((results / "manifest.json").read_text())
    spec = json.loads((results / "task" / "checks.json").read_text())
    outputs = manifest.get("outputs") or [manifest.get("output", "report.pdf")]
    if len(outputs) == 1:
        return check(results / f"{stem}{Path(outputs[0]).suffix}", spec)
    merged = {}
    for k, (name, step) in enumerate(zip(outputs, spec["steps"], strict=True), 1):
        made = results / f"{stem}.s{k}{Path(name).suffix}"
        merged |= {f"s{k}.{key}": c for key, c in check(made, step).items()}
    return merged


def folder(results: Path) -> dict:
    out = {}
    for run in sorted(results.glob("*.json")):
        if run.name in ("manifest.json", "quality.json"):
            continue
        checks = run_checks(results, run.stem)
        out[run.stem] = checks
        passed, total = score(checks)
        fails = [k for k, c in checks.items() if c["ok"] is False]
        print(f"{results.name}\t{run.stem}\t{passed}/{total}\t{' '.join(fails)}")
    (results / "quality.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        folder(Path(arg))
