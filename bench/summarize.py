"""Summarize a bench results directory: one row per run, then medians per arm.

Turns and cache reads come first because they drive cost: every turn re-reads
the whole context from cache, while output tokens are a small share.
"""

import json
import statistics
import sys
from pathlib import Path

# rupa-flagged is the old name of the flagged arm, kept so older results read.
ARMS = ("baseline", "baseline-hinted", "rupa", "rupa-flagged", "rupa-pertype", "rupa-verify")
COLS = ("turns", "cache_read", "cache_write", "input", "output", "cost_usd", "secs")


def num(d: dict, key: str, default=0):
    """A field's number, or the default if it is missing, null or not a number."""
    v = d.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def row(path: Path) -> dict | None:
    try:
        r = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(r, dict):  # valid JSON, but not a claude -p result
        return None
    u = r["usage"] if isinstance(r.get("usage"), dict) else {}
    return {
        "turns": num(r, "num_turns"),
        "cache_read": num(u, "cache_read_input_tokens"),
        "cache_write": num(u, "cache_creation_input_tokens"),
        "input": num(u, "input_tokens"),
        "output": num(u, "output_tokens"),
        "cost_usd": float(num(r, "total_cost_usd")),
        "secs": round(num(r, "duration_ms") / 1000),
        "pdf": path.with_suffix(".pdf").exists() or path.with_suffix(".html").exists(),
    }


def fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, bool):
        return "yes" if v else "NO"
    return f"{v:,}"


def main(results: Path) -> None:
    runs = {arm: [] for arm in ARMS}
    for f in sorted(results.glob("*.json")):
        arm = f.stem.rsplit("-", 1)[0]
        if arm in runs and (r := row(f)):
            runs[arm].append(r)
    arms = [a for a in ARMS if runs[a]]

    header = ("arm", "run", *COLS, "pdf")
    print("\t".join(header))
    for arm in arms:
        for i, r in enumerate(runs[arm], 1):
            print("\t".join([arm, str(i), *(fmt(r[c]) for c in COLS), fmt(r["pdf"])]))

    print("\nmedians (runs without a PDF excluded)")
    print("\t".join(("arm", "n", *COLS)))
    base = None
    for arm in arms:
        ok = [r for r in runs[arm] if r["pdf"]]
        if not ok:
            print(f"{arm}\t0\t(no successful runs)")
            continue
        med = {c: statistics.median(r[c] for r in ok) for c in COLS}
        med = {c: v if c == "cost_usd" else round(v) for c, v in med.items()}
        base = base or (med if arm == "baseline" else None)
        print("\t".join([arm, str(len(ok)), *(fmt(med[c]) for c in COLS)]))
    if base:
        print("\nvs baseline (median turns, median cost)")
        for arm in arms[1:]:
            ok = [r for r in runs[arm] if r["pdf"]]
            if ok and base["turns"] and base["cost_usd"]:
                t = statistics.median(r["turns"] for r in ok) / base["turns"] - 1
                c = statistics.median(r["cost_usd"] for r in ok) / base["cost_usd"] - 1
                print(f"{arm}\tturns {t:+.0%}\tcost {c:+.0%}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
