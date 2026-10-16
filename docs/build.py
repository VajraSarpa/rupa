"""Render the plan, guide and tutorial with Rupa itself.

Expands `@@include path lang@@` lines with the real source files, fills the
verification record, then renders docs/dist/Rupa-Plan-Guide-Tutorial.{html,pdf}.
Run from the repo root: uv run python docs/build.py
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DIST = DOCS / "dist"


def expand(m: re.Match) -> str:
    path, lang = m.group(1), m.group(2)
    code = (ROOT / path).read_text().rstrip("\n")
    fence = "````" if "```" in code else "```"
    return f"{fence}{lang}\n{code}\n{fence}"


def record() -> str:
    rec = (DOCS / "verification-record.md").read_text()
    final = json.loads((DOCS / "final-pass.json").read_text())
    rows = "\n".join(
        f"| p{r['page']} {r['kind']} | {r['verdict']} |" for r in final["rows"]
    )
    full = f"{round(final['pages'] * 2750, -3):,}"
    return (
        rec.replace("@@final-line@@", final["line"])
        .replace("@@final-rows@@", rows)
        .replace("@@sheet-count@@", str(len(final["rows"])))
        .replace("@@page-count@@", str(final["pages"]))
        .replace("@@full-cost@@", full)
    )


def main() -> int:
    src = (DOCS / "rupa-build.md").read_text()
    text = re.sub(r"^@@include (\S+) (\S+)@@$", expand, src, flags=re.MULTILINE)
    text = text.replace("@@verification-record@@", record())
    assert "@@" not in text.replace("`@@", ""), "unexpanded marker"
    DIST.mkdir(exist_ok=True)
    for ext in ("html", "pdf"):
        out = DIST / f"Rupa-Plan-Guide-Tutorial.{ext}"
        r = subprocess.run(
            ["rupa", "-o", str(out)],
            input=text,
            text=True,
            check=False,
            capture_output=True,
        )
        print(r.stdout or r.stderr, end="")
        if r.returncode:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
