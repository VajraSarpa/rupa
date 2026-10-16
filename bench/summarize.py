"""Summarize a bench results directory: one row per run, then medians per arm.

Turns and cache reads come first because they drive cost: every turn re-reads
the whole context from cache, while output tokens are a small share.
"""

import json
import statistics
import sys
from pathlib import Path

ARMS = ("baseline", "rupa", "rupa-verify")
COLS = ("turns", "cache_read", "cache_write", "input", "output", "cost_usd", "secs")


def row(path: Path) -> dict | None:
    try:
        r = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    u = r.get("usage", {})
    return {
        "turns": r.get("num_turns", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cost_usd": r.get("total_cost_usd", 0.0),
        "secs": round(r.get("duration_ms", 0) / 1000),
        "pdf": path.with_suffix(".pdf").exists(),
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

    header = ("arm", "run", *COLS, "pdf")
    print("\t".join(header))
    for arm in ARMS:
        for i, r in enumerate(runs[arm], 1):
            print("\t".join([arm, str(i), *(fmt(r[c]) for c in COLS), fmt(r["pdf"])]))

    print("\nmedians (runs without a PDF excluded)")
    print("\t".join(("arm", "n", *COLS)))
    base = None
    for arm in ARMS:
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
        for arm in ARMS[1:]:
            ok = [r for r in runs[arm] if r["pdf"]]
            if ok and base["turns"] and base["cost_usd"]:
                t = statistics.median(r["turns"] for r in ok) / base["turns"] - 1
                c = statistics.median(r["cost_usd"] for r in ok) / base["cost_usd"] - 1
                print(f"{arm}\tturns {t:+.0%}\tcost {c:+.0%}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
