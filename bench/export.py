"""Export every benchmark run as data: bench/data/runs.csv and summary.csv.

One row per run, read from its result JSON, its Claude Code transcript and
its PDF, so the published numbers can be checked without the raw folders:

    uv run python bench/export.py [bench/results] [bench/data]

Context is measured from the transcript: each API call's input, cache-read
and cache-write tokens add up to the context it read. "Added" is the run's
largest context minus its first, which takes out Claude Code's own starting
context (it changed between benchmark days). Each PDF is checked with the
current `rupa verify` rules, on a copy, so the results folders stay clean.
"""

import csv
import json
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

from rupa.verify import load_wants, verify

PROJECTS = Path.home() / ".claude" / "projects"

# What each results folder was, and which published numbers come from it.
FOLDERS = {
    "20261015-223853": ("report", "pilot, one run per arm", ""),
    "20261015-230620": ("report", "first result, before page budgets", "case study: first benchmark"),
    "20261015-235429": ("report", "page budgets and flagged-only sheets", "case study: second result"),
    "20261016-000922-guide": ("guide", "first guide run, word-based cut hints", ""),
    "20261016-004331-guide": ("guide", "with bundled fonts", ""),
    "20261016-062258-guide": ("guide", "line-based cut hints", "README, cost analysis: guide"),
    "20261016-065003-report": ("report", "report on the current build", "README, cost analysis: report"),
    "20261016-072202-tight": ("tight", "must cut; Rupa arms only", "build guide: tight task"),
    "20261016-080149-wide": ("wide", "single run, before the overflow detail", "case study: 13 points over"),
    "20261016-084958-wide": ("wide", "single run, after the split rule", ""),
    "20261016-085325-wide": ("wide", "all arms, before the wide-table rule", "README, cost analysis: wide baseline"),
    "20261016-094105-wide": ("wide", "Rupa arms, after the wide-table rule", "README, cost analysis: wide with Rupa"),
}
ARMS = ("baseline", "rupa", "rupa-flagged", "rupa-pertype", "rupa-verify")
RUN_COLS = (
    "folder", "task", "build", "arm", "run", "model", "turns", "cost_usd", "secs",
    "input", "output", "cache_read", "cache_write", "api_calls",
    "context_start", "context_peak", "context_added",
    "pdf", "verify_passed", "verify_total", "verify_failed",
)
NUMERIC = ("turns", "cost_usd", "secs", "output", "cache_read", "cache_write", "context_added")


def context(session_id: str) -> list[int]:
    """Tokens read by each distinct API call in the run's transcript."""
    path = next(PROJECTS.glob(f"*/{session_id}.jsonl"), None)
    if path is None:
        return []
    seen, sizes = set(), []
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event.get("type") != "assistant":
            continue
        message = event["message"]
        if message.get("id") in seen:  # one call can span several transcript lines
            continue
        seen.add(message.get("id"))
        u = message.get("usage", {})
        sizes.append(
            u.get("input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
        )
    return sizes


def check(pdf: Path, scratch: Path) -> tuple[int, int, str]:
    copy = scratch / pdf.name
    shutil.copy(pdf, copy)
    report = verify(copy, load_wants(None), scratch / f"{pdf.stem}.verify")
    failed = [c.id for c in report.checks if not c.ok]
    return len(report.checks) - len(failed), len(report.checks), " ".join(failed)


def runs(results: Path, scratch: Path) -> list[dict]:
    rows = []
    for folder in sorted(p for p in results.iterdir() if p.is_dir()):
        task, build, _ = FOLDERS.get(folder.name, ("?", "unlabelled", ""))
        for arm in ARMS:
            for result in sorted(folder.glob(f"{arm}-[0-9].json")):
                r = json.loads(result.read_text())
                u = r.get("usage", {})
                sizes = context(r.get("session_id", ""))
                pdf = result.with_suffix(".pdf")
                passed, total, failed = check(pdf, scratch) if pdf.is_file() else (0, 0, "")
                rows.append({
                    "folder": folder.name, "task": task, "build": build, "arm": arm,
                    "run": result.stem.rsplit("-", 1)[1],
                    "model": ",".join(r.get("modelUsage", {})),
                    "turns": r.get("num_turns", 0),
                    "cost_usd": round(r.get("total_cost_usd", 0.0), 4),
                    "secs": round(r.get("duration_ms", 0) / 1000),
                    "input": u.get("input_tokens", 0),
                    "output": u.get("output_tokens", 0),
                    "cache_read": u.get("cache_read_input_tokens", 0),
                    "cache_write": u.get("cache_creation_input_tokens", 0),
                    "api_calls": len(sizes),
                    "context_start": sizes[0] if sizes else "",
                    "context_peak": max(sizes) if sizes else "",
                    "context_added": max(sizes) - sizes[0] if sizes else "",
                    "pdf": "yes" if pdf.is_file() else "no",
                    "verify_passed": passed, "verify_total": total, "verify_failed": failed,
                })
    return rows


def summary(rows: list[dict]) -> list[dict]:
    out = []
    keys = sorted({(r["folder"], r["arm"]) for r in rows}, key=lambda k: (k[0], ARMS.index(k[1])))
    for folder, arm in keys:
        group = [r for r in rows if r["folder"] == folder and r["arm"] == arm]
        row = {"folder": folder, "task": group[0]["task"], "build": group[0]["build"],
               "used_in": FOLDERS.get(folder, ("", "", ""))[2], "arm": arm, "runs": len(group)}
        for col in NUMERIC:
            values = [r[col] for r in group if r[col] != ""]
            row[f"median_{col}"] = round(statistics.median(values), 4) if values else ""
        row["pdfs_passing"] = sum(r["verify_total"] > 0 and r["verify_failed"] == "" for r in group)
        out.append(row)
    return out


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    results = Path(sys.argv[1] if len(sys.argv) > 1 else "bench/results")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "bench/data")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rows = runs(results, Path(tmp))
    write(out / "runs.csv", rows)
    write(out / "summary.csv", summary(rows))
    print(f"export: {len(rows)} runs to {out}/runs.csv and summary.csv")


if __name__ == "__main__":
    main()
