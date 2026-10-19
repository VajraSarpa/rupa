"""Read the result events out of a run's stream-json file.

    python3 bench/result.py RUN.jsonl STEPS EXIT   prints the run's result object
    python3 bench/result.py --session RUN.jsonl    prints the last session id
    python3 bench/result.py --split PROMPT.txt DIR writes DIR/1.txt, 2.txt, ...

With one step the result is the event exactly as `--output-format json` prints
it. A session run has one result event per step; its turns, cost, time and
token usage are summed, and each step's event is kept under "steps". If fewer
results than steps came back, the run failed: "error" says so.

A session task's prompt.txt holds one prompt per step, separated by lines of ---.
"""

import json
import re
import sys
from pathlib import Path

SUMMED = ("num_turns", "total_cost_usd", "duration_ms", "duration_api_ms")


def results(path: str) -> list[dict]:
    found = []
    with open(path, errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                found.append(event)
    return found


def combined(found: list[dict], steps: int, exit_code: int) -> dict:
    if not found:
        return {"error": "no result event", "exit": exit_code}
    if steps == 1:
        return found[-1]
    out = dict(found[-1])
    for key in SUMMED:
        out[key] = sum(r.get(key) or 0 for r in found)
    usage = {}
    for r in found:
        for k, v in (r.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                usage[k] = usage.get(k, 0) + v
    out["usage"] = usage
    out["steps"] = found
    if len(found) < steps:
        out["error"] = f"{len(found)} of {steps} steps returned a result"
        out["exit"] = exit_code
    return out


def split(prompt: Path, out: Path) -> int:
    parts = [p.strip() for p in re.split(r"(?m)^---\s*$", prompt.read_text())]
    out.mkdir(parents=True, exist_ok=True)
    parts = [p for p in parts if p]
    for n, part in enumerate(parts, 1):
        (out / f"{n}.txt").write_text(part + "\n")
    return len(parts)


if __name__ == "__main__":
    if sys.argv[1] == "--session":
        found = results(sys.argv[2])
        print(found[-1].get("session_id", "") if found else "")
    elif sys.argv[1] == "--split":
        print(split(Path(sys.argv[2]), Path(sys.argv[3])))
    else:
        print(json.dumps(combined(results(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]))))
