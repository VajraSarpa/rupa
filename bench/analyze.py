"""Per-run detail for a bench results folder, read from the Claude Code transcripts.

For each run: turns, cost, PDF word count, Edits and net words cut, every
distinct `rupa: wrote` status line, and with --calls every tool call.

Usage: python3 bench/analyze.py bench/results/<stamp>-<task> [--calls]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# Matches status lines inside JSON-escaped transcript text.
WROTE = re.compile(r"rupa: wrote[^\"\\]*")
PROJECTS = Path.home() / ".claude" / "projects"


def transcript(session_id: str) -> Path | None:
    return next(PROJECTS.glob(f"*/{session_id}.jsonl"), None)


def words(pdf: Path) -> int | str:
    if not pdf.exists():
        return "no pdf"
    try:
        out = subprocess.run(
            ["pdftotext", str(pdf), "-"], check=False, capture_output=True, text=True
        ).stdout
    except FileNotFoundError:
        return "?"
    return len(out.split())


def main(results: Path, show_calls: bool) -> None:
    for path in sorted(results.glob("*-[0-9].json")):
        name = path.stem
        try:
            run = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"== {name}: bad json")
            continue
        sid = run.get("session_id")
        t = transcript(sid) if sid else None
        calls, wrote, edits = [], [], []
        if t:
            raw = t.read_text()
            wrote = list(dict.fromkeys(WROTE.findall(raw)))
            for line in raw.splitlines():
                msg = json.loads(line)
                if msg.get("type") != "assistant":
                    continue
                for c in msg["message"].get("content", []):
                    if c.get("type") != "tool_use":
                        continue
                    inp = c["input"]
                    desc = inp.get("command") or inp.get("file_path") or inp.get("skill") or ""
                    calls.append(f"{c['name']}: {desc.splitlines()[0][:100] if desc else ''}")
                    if c["name"] == "Edit":
                        edits.append(
                            len(inp["old_string"].split()) - len(inp["new_string"].split())
                        )
        print(
            f"== {name}: turns={run.get('num_turns')} cost=${run.get('total_cost_usd', 0):.2f}"
            f" words={words(results / f'{name}.pdf')} edits={len(edits)} words_cut={sum(edits)}"
        )
        for w in wrote:
            print("   ", w.strip()[:160])
        if show_calls:
            for c in calls:
                print("      ", c)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), "--calls" in sys.argv)
