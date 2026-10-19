"""Judge bench v2 outputs from their page images (see bench/PREREG.md).

    uv run python bench/judge.py rate  bench/results/<folder> [...]
    uv run python bench/judge.py pairs bench/results/<folder> [...]

rate:  each output alone, against its task's checklist (`judge` in checks.json):
       every item met / partly / not_met, plus readability and layout 1-5.
       Writes <folder>/judge/<run>.json.
pairs: rupa-verify run i against baseline run i and baseline-hinted run i, in
       the same folder, shown as A and B in a seeded random order. Writes
       <folder>/judge/pair-<other arm>-<i>.json, with which arm was A.

The judge is `claude -p` (JUDGE_MODEL, default claude-sonnet-5-5) with only the
Read tool, run in a temporary folder holding nothing but the page images under
neutral names, so neither the prompt nor a path says which arm made what.
PDF pages are rendered at 100 dpi with pdftoppm; an HTML output is printed to
PDF by headless Chrome first. Existing judge files are kept, so a rerun only
fills gaps. JUDGE_JOBS (default 4) calls run at once.
"""

import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL = os.environ.get("JUDGE_MODEL", "claude-sonnet-5-5")
JOBS = int(os.environ.get("JUDGE_JOBS", "4"))
ISOLATE = ["--setting-sources", "project", "--strict-mcp-config"]
DPI = 100
CHROME = "google-chrome"

VERDICT = {"type": "string", "enum": ["met", "partly", "not_met"]}
RATE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "integer"},
                    "verdict": VERDICT,
                    "evidence": {"type": "string"},
                },
                "required": ["item", "verdict", "evidence"],
            },
        },
        "readability": {"type": "integer", "minimum": 1, "maximum": 5},
        "layout": {"type": "integer", "minimum": 1, "maximum": 5},
        "notes": {"type": "string"},
    },
    "required": ["items", "readability", "layout", "notes"],
}
CHOICE = {"type": "string", "enum": ["A", "B", "tie"]}
PAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "does_what_was_asked": CHOICE,
        "layout_and_readability": CHOICE,
        "reason": {"type": "string"},
    },
    "required": ["does_what_was_asked", "layout_and_readability", "reason"],
}

RATE_PROMPT = """You are judging a document someone asked for. The request was:

<request>
{request}
</request>

The document's pages are these image files, in order: {pages}. Read every page.

For each numbered checklist item, say whether the document meets it (met,
partly or not_met), with a few words of evidence from the pages:

{checklist}

Then rate, from 1 (poor) to 5 (excellent):
- readability: can a reader take it in easily (type size, contrast, line
  length, clear headings)?
- layout: is the page well used, with nothing overflowing, clipped, overlapping
  or awkwardly broken across pages?

Judge only what is on the pages. Don't reward or penalise a visual style for
being plain or distinctive; judge whether it works."""

PAIR_PROMPT = """Two documents, A and B, were each made for this request:

<request>
{request}
</request>

Document A's pages, in order: {a}.
Document B's pages, in order: {b}.
Read every page of both.

1. does_what_was_asked: which better does what the request asked (content,
   completeness, accuracy, the length and format asked for)?
2. layout_and_readability: which is better laid out and easier to read?

Answer A, B or tie for each, and give a short reason. Don't prefer either for
its visual style or for being plain or distinctive; judge whether it works."""


def outputs(folder: Path) -> list[tuple[str, Path, str]]:
    """(run stem, output file, the prompt it answered) for every output in a folder."""
    manifest = json.loads((folder / "manifest.json").read_text())
    names = manifest.get("outputs") or [manifest["output"]]
    found = []
    for run in sorted(folder.glob("*.json")):
        if run.name == "manifest.json" or "-" not in run.stem:
            continue
        for k, name in enumerate(names, 1):
            stem = run.stem if len(names) == 1 else f"{run.stem}.s{k}"
            made = folder / f"{stem}{Path(name).suffix}"
            prompt = (folder / "steps" / f"{k}.txt").read_text().strip()
            if made.is_file() and made.stat().st_size:
                found.append((stem, made, prompt))
    return found


def checklist(folder: Path, stem: str) -> list[str]:
    spec = json.loads((folder / "task" / "checks.json").read_text())
    if "steps" in spec:
        spec = spec["steps"][int(stem.rsplit(".s", 1)[1]) - 1]
    return spec.get("judge", [])


def pages(folder: Path, stem: str, made: Path) -> list[Path]:
    """Page images for an output, rendered once into <folder>/pages/<stem>/."""
    out = folder / "pages" / stem
    if out.is_dir() and any(out.glob("p-*.png")):
        return sorted(out.glob("p-*.png"))
    out.mkdir(parents=True, exist_ok=True)
    pdf = made
    if made.suffix == ".html":
        pdf = out / "print.pdf"
        subprocess.run(
            [CHROME, "--headless=new", "--no-pdf-header-footer", "--disable-gpu",
             f"--print-to-pdf={pdf}", made.resolve().as_uri()],
            capture_output=True, timeout=120, check=False,
        )
    if pdf.is_file():
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(pdf), str(out / "p")],
                       capture_output=True, timeout=300, check=False)
    # pdftoppm pads page numbers to the page count's width; give them one width.
    for p in out.glob("p-*.png"):
        n = int(p.stem.split("-")[1])
        p.rename(out / f"p-{n:03d}.png")
    return sorted(out.glob("p-*.png"))


def inputs_note(folder: Path) -> str:
    names = sorted(p.name for p in (folder / "task" / "inputs").glob("*"))
    if not names:
        return ""
    return ("\n\nThe files the request refers to are in this folder too: "
            f"{', '.join(names)}. Read them to check the document against them.")


def ask(prompt: str, schema: dict, images: dict[str, Path], folder: Path) -> dict:
    """One judge call in a folder holding only `images` (new name -> source) and
    the task's input files, which checklist items may need."""
    with tempfile.TemporaryDirectory(prefix="judge-") as tmp:
        for name, src in images.items():
            shutil.copy(src, Path(tmp) / name)
        if (folder / "task" / "inputs").is_dir():
            shutil.copytree(folder / "task" / "inputs", tmp, dirs_exist_ok=True)
        prompt += inputs_note(folder)
        done = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--model", MODEL,
             "--tools", "Read", "--allowedTools", "Read", *ISOLATE,
             "--json-schema", json.dumps(schema)],
            cwd=tmp, capture_output=True, text=True, timeout=900, check=False,
        )
    try:
        result = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"error": f"exit {done.returncode}: {done.stderr[-500:]}"}
    return {
        "verdict": result.get("structured_output"),
        "model": MODEL,
        "cost_usd": result.get("total_cost_usd"),
        "turns": result.get("num_turns"),
        "is_error": result.get("is_error"),
    }


def rate_one(folder: Path, stem: str, made: Path, request: str) -> str:
    target = folder / "judge" / f"{stem}.json"
    if target.exists():
        return f"{folder.name} {stem}: kept"
    items = checklist(folder, stem)
    imgs = pages(folder, stem, made)
    verdict: dict
    if not imgs:
        verdict = {"error": "no pages rendered"}
    else:
        names = {f"page-{n:02d}.png": p for n, p in enumerate(imgs, 1)}
        verdict = ask(RATE_PROMPT.format(
            request=request, pages=", ".join(names),
            checklist="\n".join(f"{n}. {item}" for n, item in enumerate(items, 1)),
        ), RATE_SCHEMA, names, folder)
    verdict.update({"run": stem, "checklist": items, "pages": len(imgs)})
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(verdict, indent=2))
    return f"{folder.name} {stem}: {verdict.get('error') or 'rated'}"


def pair_one(folder: Path, other: str, stem_r: str, stem_o: str, files: dict,
             request: str) -> str:
    label = stem_o.replace(f"{other}-", "", 1)
    target = folder / "judge" / f"pair-{other}-{label}.json"
    if target.exists():
        return f"{folder.name} pair {other} {label}: kept"
    rupa_a = random.Random(f"{folder.name}:{other}:{label}").random() < 0.5
    first, second = (stem_r, stem_o) if rupa_a else (stem_o, stem_r)
    a_imgs = pages(folder, first, files[first])
    b_imgs = pages(folder, second, files[second])
    names = {f"A-page-{n:02d}.png": p for n, p in enumerate(a_imgs, 1)}
    b_names = {f"B-page-{n:02d}.png": p for n, p in enumerate(b_imgs, 1)}
    verdict = ask(PAIR_PROMPT.format(request=request, a=", ".join(names),
                                     b=", ".join(b_names)), PAIR_SCHEMA, names | b_names, folder)
    verdict.update({"A": first, "B": second, "rupa_is": "A" if rupa_a else "B",
                    "pages": [len(a_imgs), len(b_imgs)]})
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(verdict, indent=2))
    return f"{folder.name} pair {other} {label}: {verdict.get('error') or 'judged'}"


def rate(folders: list[Path]) -> list:
    return [(rate_one, (f, stem, made, req)) for f in folders for stem, made, req in outputs(f)]


def pairs(folders: list[Path]) -> list:
    jobs = []
    for f in folders:
        found = {stem: (made, req) for stem, made, req in outputs(f)}
        files = {stem: made for stem, (made, _) in found.items()}
        for stem_r, (_, req) in found.items():
            if not stem_r.startswith("rupa-verify-"):
                continue
            suffix = stem_r.removeprefix("rupa-verify-")
            for other in ("baseline", "baseline-hinted"):
                if f"{other}-{suffix}" in found:
                    jobs.append((pair_one, (f, other, stem_r, f"{other}-{suffix}", files, req)))
    return jobs


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("rate", "pairs"):
        sys.exit(__doc__)
    folders = [Path(a) for a in sys.argv[2:]]
    # Render every output's pages first: one output can be in two pairs at once.
    with ThreadPoolExecutor(JOBS) as pool:
        list(pool.map(lambda o: pages(*o), [(f, s, m) for f in folders for s, m, _ in outputs(f)]))
    jobs = rate(folders) if sys.argv[1] == "rate" else pairs(folders)
    with ThreadPoolExecutor(JOBS) as pool:
        for line in pool.map(lambda job: job[0](*job[1]), jobs):
            print(line, flush=True)
