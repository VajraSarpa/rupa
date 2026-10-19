"""Apply bench/PREREG.md's rules to the bench v2 results.

    uv run python bench/analyze_v2.py [bench/results] [--model claude-opus-5-5]

Prints, per task and arm, runs, successes, cost per success, median cost,
turns, time, context added, mechanical quality and judge scores; then H1-H3
for rupa-verify against each baseline on the held-out tasks, the same
numbers on the seen tasks without a pass rule, and the pairwise judge tally.
"""

import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import export  # bench/export.py, next to this file

HELD = ("cv", "lab", "handbook", "notes", "html", "revise")
SEEN = ("report", "guide", "tight", "wide")
RUPA = "rupa-verify"
BASELINES = ("baseline", "baseline-hinted")
SCORE = {"met": 1.0, "partly": 0.5, "not_met": 0.0}
BOOT = 10_000


def judged(folder: Path, stem: str) -> dict | None:
    path = folder / "judge" / f"{stem}.json"
    if not path.exists():
        return None
    verdict = json.loads(path.read_text()).get("verdict") or {}
    items = [SCORE[i["verdict"]] for i in verdict.get("items", []) if i.get("verdict") in SCORE]
    if not items:
        return None
    return {"req": statistics.mean(items), "readability": verdict.get("readability"),
            "layout": verdict.get("layout")}


def attach_judge(results: Path, rows: list[dict]) -> None:
    for r in rows:
        folder = results / r["folder"]
        steps = json.loads((folder / "manifest.json").read_text()).get("steps", 1)
        stems = [f"{r['arm']}-{r['run']}"] if steps == 1 else [
            f"{r['arm']}-{r['run']}.s{k}" for k in range(1, steps + 1)]
        found = [j for s in stems if (j := judged(folder, s))]
        for key in ("req", "readability", "layout"):
            values = [j[key] for j in found if j[key] is not None]
            r[f"judge_{key}"] = statistics.mean(values) if values else None


def pair_tally(results: Path, rows: list[dict]) -> dict:
    """{(task, model, other): {question: [rupa wins, losses, ties]}}"""
    tally = {}
    folders = {r["folder"]: (r["task"], r["model"]) for r in rows}
    for name, (task, model) in folders.items():
        for path in sorted((results / name / "judge").glob("pair-*.json")):
            p = json.loads(path.read_text())
            if not p.get("verdict"):
                continue
            other = p["B"].rsplit("-", 1)[0] if p["rupa_is"] == "A" else p["A"].rsplit("-", 1)[0]
            entry = tally.setdefault((task, model, other), {
                "does_what_was_asked": [0, 0, 0], "layout_and_readability": [0, 0, 0]})
            for q in entry:
                choice = p["verdict"][q]
                entry[q][0 if choice == p["rupa_is"] else 2 if choice == "tie" else 1] += 1
    return tally


def by(rows: list[dict], task: str, arm: str) -> list[dict]:
    return [r for r in rows if r["task"] == task and r["arm"] == arm]


def cost_per_success(group: list[dict]) -> float | None:
    ok = [r for r in group if r["made_output"] and not r["contaminated"]]
    return sum(r["cost_usd"] for r in group) / len(ok) if ok else None


def med(values: list) -> float | None:
    values = [v for v in values if v not in (None, "")]
    return statistics.median(values) if values else None


def geo_ratio(rows: list[dict], tasks: tuple, other: str, rng=None) -> float | None:
    """Geometric mean over tasks of median cost ratio, rupa-verify / other.
    With rng, each arm's runs are resampled with replacement first."""
    logs = []
    for task in tasks:
        a, b = by(rows, task, RUPA), by(rows, task, other)
        if not a or not b:
            continue
        if rng:
            a = [rng.choice(a) for _ in a]
            b = [rng.choice(b) for _ in b]
        ma, mb = med([r["cost_usd"] for r in a]), med([r["cost_usd"] for r in b])
        if ma and mb:
            logs.append(math.log(ma / mb))
    return math.exp(statistics.mean(logs)) if logs else None


def interval(rows: list[dict], tasks: tuple, other: str) -> tuple[float, float]:
    rng = random.Random(0)
    draws = sorted(g for _ in range(BOOT) if (g := geo_ratio(rows, tasks, other, rng)))
    return draws[int(0.05 * len(draws))], draws[int(0.95 * len(draws)) - 1]


def fmt(v, digits=2) -> str:
    if v is None or v == "":
        return "-"
    return f"{v:.{digits}f}" if isinstance(v, float) else str(v)


def table(rows: list[dict], tasks: tuple) -> list[str]:
    out = [("| task | arm | runs | ok | cost/success | median cost | turns | secs | "
            "context added | mech. quality | judge req | readability | layout |"),
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for task in tasks:
        for arm in (*BASELINES, RUPA):
            g = by(rows, task, arm)
            if not g:
                continue
            ok = [r for r in g if r["made_output"] and not r["contaminated"]]
            qp, qt = sum(r["quality_passed"] for r in ok), sum(r["quality_total"] for r in ok)
            out.append("| " + " | ".join([
                task, arm, str(len(g)), str(len(ok)), fmt(cost_per_success(g), 3),
                fmt(med([r["cost_usd"] for r in g]), 3), fmt(med([r["turns"] for r in ok]), 0),
                fmt(med([r["secs"] for r in ok]), 0), fmt(med([r["context_added"] for r in ok]), 0),
                fmt(qp / qt if qt else None), fmt(med([r["judge_req"] for r in ok])),
                fmt(med([r["judge_readability"] for r in ok]), 1),
                fmt(med([r["judge_layout"] for r in ok]), 1)]) + " |")
    return out


def hypotheses(rows: list[dict], tally: dict, model: str, tasks: tuple, rules: bool) -> list[str]:
    out = []
    for other in BASELINES:
        present = [t for t in tasks if by(rows, t, RUPA) and by(rows, t, other)]
        if not present:
            continue
        cheaper = [t for t in present
                   if (a := cost_per_success(by(rows, t, RUPA))) is not None
                   and ((b := cost_per_success(by(rows, t, other))) is None or a < b)]
        g = geo_ratio(rows, tuple(present), other)
        lo, hi = interval(rows, tuple(present), other)
        h1 = len(cheaper) >= 4 and hi < 1
        ra, rb = ([r["judge_req"] for t in present for r in by(rows, t, arm)
                   if r["judge_req"] is not None] for arm in (RUPA, other))
        mean_a = statistics.mean(ra) if ra else None
        mean_b = statistics.mean(rb) if rb else None
        wins = losses = ties = 0
        for t in present:
            w, lo_, ti = tally.get((t, model, other), {}).get("does_what_was_asked", [0, 0, 0])
            wins, losses, ties = wins + w, losses + lo_, ties + ti
        decided = wins + losses
        h2 = (mean_a is not None and mean_b is not None and mean_a >= mean_b - 0.05
              and decided > 0 and losses <= decided / 2)
        def fails(arm, t):
            return sum(not (r["made_output"] and not r["contaminated"]) for r in by(rows, t, arm))

        worse = [t for t in present if fails(RUPA, t) > fails(other, t) + 1]
        h3 = not worse
        out += [
            f"### {RUPA} vs {other} ({len(present)} tasks)",
            "",
            f"- H1 cost: cheaper per success on {len(cheaper)} of {len(present)} "
            f"({', '.join(cheaper) or 'none'}); geometric mean median-cost ratio {g:.2f}, "
            f"90% interval {lo:.2f}-{hi:.2f}" + (f" -> **{'holds' if h1 else 'fails'}**" if rules else ""),
            f"- H2 quality: judge requirement score {fmt(mean_a)} vs {fmt(mean_b)}; pairwise "
            f"'does what was asked' {wins} wins, {losses} losses, {ties} ties"
            + (f" -> **{'holds' if h2 else 'fails'}**" if rules else ""),
            f"- H3 reliability: tasks where {RUPA} failed more than {other} + 1: "
            f"{', '.join(worse) or 'none'}" + (f" -> **{'holds' if h3 else 'fails'}**" if rules else ""),
            "",
        ]
    return out


def main(args: list[str]) -> None:
    model = "claude-opus-5-5"
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1]
        args = args[:i] + args[i + 2:]
    results = Path(args[0] if args else "bench/results")
    rows = [r for r in export.v2_runs(results) if r["model"] == model]
    attach_judge(results, rows)
    tally = pair_tally(results, rows)
    lines = [f"# Bench v2 analysis: {model}", "", f"{len(rows)} runs.", "",
             "## Held-out tasks", "", *table(rows, HELD), "",
             *hypotheses(rows, tally, model, HELD, rules=True),
             "## Seen tasks (no pass rule)", "", *table(rows, SEEN), "",
             *hypotheses(rows, tally, model, SEEN, rules=False),
             "## Session (no pass rule)", "", *table(rows, ("session",)), "",
             "## Pairwise judge", "",
             "| task | vs | asked: wins / losses / ties | layout: wins / losses / ties |",
             "|---|---|---|---|"]
    for (task, _, other), q in sorted(tally.items()):
        lines.append(f"| {task} | {other} | {'/'.join(map(str, q['does_what_was_asked']))} | "
                     f"{'/'.join(map(str, q['layout_and_readability']))} |")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
