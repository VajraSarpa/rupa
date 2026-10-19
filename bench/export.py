"""Export every benchmark run as data: bench/data/runs.csv and summary.csv.

One row per run, read from its result JSON, its Claude Code transcript and
its PDF, so the published numbers can be checked without the raw folders:

    uv run python bench/export.py [bench/results] [bench/data]
    uv run python bench/export.py --v2 [bench/results] [bench/data-v2]

Bench v2 folders (those with a manifest.json) are exported only with --v2; see
`v2_runs` below.

Context is measured from the transcript: each API call's input, cache-read
and cache-write tokens add up to the context it read. "Added" is the run's
largest context minus its first, which takes out Claude Code's own starting
context (it changed between benchmark days). Each PDF is checked with the
current `rupa verify` rules, on a copy, so the results folders stay clean.
"""

import csv
import json
import re
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
    return context_of(path)


def events(path: Path) -> list[dict]:
    """The JSON objects in a JSONL file, skipping anything that isn't one."""
    out = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            out.append(event)
    return out


def context_of(path: Path) -> list[int]:
    """Tokens read by each distinct API call in a transcript or stream-json file."""
    seen, sizes = set(), []
    for event in events(path):
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
        if (folder / "manifest.json").exists():
            continue  # bench v2: exported with --v2
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


V2_NUMERIC = ("turns", "cost_usd", "secs", "context_added")
# Commands and writes that tell how a run made its document.
RAN_RUPA = re.compile(r"(^|[\s;&|(])rupa\b")
MARKUP = re.compile(r"\.(html?|css|tex|typ)$")


def tool_calls(stream: list[dict]) -> list[dict]:
    calls = []
    for event in stream:
        if event.get("type") == "assistant":
            for c in event.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    calls.append(c)
    return calls


def v2_runs(results: Path) -> list[dict]:
    """One row per bench v2 run, from its folder alone (no ~/.claude needed)."""
    sys.path.insert(0, str(Path(__file__).parent))
    import quality  # bench/quality.py, next to this file

    rows = []
    for folder in sorted(p for p in results.iterdir() if (p / "manifest.json").exists()):
        manifest = json.loads((folder / "manifest.json").read_text())
        order = {(e["arm"], e["run"]): e for e in events(folder / "manifest.jsonl")}
        for arm, i in sorted(order):
            r = json.loads((folder / f"{arm}-{i}.json").read_text())
            stream = events(folder / f"{arm}-{i}.jsonl")
            init = next((e for e in stream if e.get("subtype") == "init"), {})
            calls = tool_calls(stream)
            sizes = context_of(folder / f"{arm}-{i}.jsonl")
            u = r.get("usage") or {}
            q = quality.run_checks(folder, f"{arm}-{i}")
            exists = [c["ok"] for k, c in q.items() if k.rsplit(".", 1)[-1] == "exists"]
            decided = [k for k, c in q.items() if c["ok"] is not None]
            skills = init.get("skills") or []
            rupa_skill = any("render" in s and "rupa" in s for s in skills)
            ran_rupa = any(RAN_RUPA.search(c.get("input", {}).get("command") or "")
                           for c in calls if c.get("name") == "Bash")
            wrote_markup = sum(c.get("name") == "Write"
                               and bool(MARKUP.search(c.get("input", {}).get("file_path") or ""))
                               for c in calls)
            rows.append({
                "folder": folder.name, "task": manifest["task"], "model": manifest["model"],
                "freeze_tag": manifest.get("freeze_tag", ""), "arm": arm, "run": i,
                "position": order[(arm, i)]["position"], "exit": order[(arm, i)]["exit"],
                "timed_out": order[(arm, i)]["exit"] == 124,
                "result": "error" not in r, "is_error": bool(r.get("is_error")),
                "made_output": bool(exists) and all(exists),
                "turns": r.get("num_turns") or 0,
                "cost_usd": round(r.get("total_cost_usd") or 0.0, 4),
                "secs": round((r.get("duration_ms") or order[(arm, i)]["secs"] * 1000) / 1000),
                "input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0),
                "cache_read": u.get("cache_read_input_tokens", 0),
                "cache_write": u.get("cache_creation_input_tokens", 0),
                "api_calls": len(sizes),
                "context_start": sizes[0] if sizes else "",
                "context_peak": max(sizes) if sizes else "",
                "context_added": max(sizes) - sizes[0] if sizes else "",
                "tool_calls": len(calls),
                "rupa_skill_loaded": rupa_skill, "ran_rupa": ran_rupa,
                "wrote_markup": wrote_markup,
                "contaminated": arm.startswith("baseline") and (rupa_skill or ran_rupa),
                "quality_passed": sum(bool(q[k]["ok"]) for k in decided),
                "quality_total": len(decided),
                "quality_failed": " ".join(k for k in decided if not q[k]["ok"]),
                "quality_unknown": " ".join(k for k, c in q.items() if c["ok"] is None
                                            and k.rsplit(".", 1)[-1] != "words"),
                "words": sum(int(c["detail"]) for k, c in q.items()
                             if k.rsplit(".", 1)[-1] == "words"),
            })
    return rows


def quartiles(values: list[float]) -> tuple[float, float, float]:
    if len(values) == 1:
        return values[0], values[0], values[0]
    q1, q2, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q1, q2, q3


def v2_summary(rows: list[dict]) -> list[dict]:
    """Per task, model and arm. Failed and contaminated runs count against the arm:
    cost_per_success is every run's cost over the runs that made the output."""
    out = []
    for key in sorted({(r["task"], r["model"], r["arm"]) for r in rows}):
        group = [r for r in rows if (r["task"], r["model"], r["arm"]) == key]
        ok = [r for r in group if r["made_output"] and not r["contaminated"]]
        row = {"task": key[0], "model": key[1], "arm": key[2], "runs": len(group),
               "successes": len(ok), "success_rate": round(len(ok) / len(group), 3),
               "contaminated": sum(r["contaminated"] for r in group),
               "timed_out": sum(r["timed_out"] for r in group),
               "cost_total": round(sum(r["cost_usd"] for r in group), 4),
               "cost_per_success": round(sum(r["cost_usd"] for r in group) / len(ok), 4)
               if ok else ""}
        for col in V2_NUMERIC:
            values = [r[col] for r in ok if r[col] != ""]
            q1, q2, q3 = quartiles(values) if values else ("", "", "")
            row.update({f"q1_{col}": q1, f"median_{col}": q2, f"q3_{col}": q3})
        passed = sum(r["quality_passed"] for r in ok)
        total = sum(r["quality_total"] for r in ok)
        row["quality_rate"] = round(passed / total, 3) if total else ""
        row["outputs_all_checks_pass"] = sum(r["quality_failed"] == "" for r in ok)
        out.append(row)
    return out


def main_v2(args: list[str]) -> None:
    results = Path(args[0] if args else "bench/results")
    out = Path(args[1] if len(args) > 1 else "bench/data-v2")
    rows = v2_runs(results)
    if not rows:
        sys.exit(f"export: no bench v2 folders in {results}")
    out.mkdir(parents=True, exist_ok=True)
    write(out / "runs.csv", rows)
    write(out / "summary.csv", v2_summary(rows))
    print(f"export: {len(rows)} v2 runs to {out}/runs.csv and summary.csv")


def main() -> None:
    if sys.argv[1:2] == ["--v2"]:
        main_v2(sys.argv[2:])
        return
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
