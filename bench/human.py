"""Blind human judging of bench v2 pairs (see bench/PREREG.md, "Human").

    uv run python bench/human.py make  bench/results OUT_DIR
    uv run python bench/human.py score bench/results OUT_DIR ANSWERS.json

make:  draws 15 pairs (seed 0) from the Opus held-out pairs: rupa-verify run i
       against baseline or baseline-hinted run i. Writes OUT_DIR/index.html,
       which shows each request and the two documents' pages as A and B in a
       seeded random order, with the judge's two questions. The page builds an
       answer code to paste back. The answer key goes to OUT_DIR/key.json;
       don't open it before judging.
score: compares the answers with the key and with the LLM judge's verdicts on
       the same pairs.
"""

import html
import json
import random
import shutil
import sys
from pathlib import Path

HELD = ("cv", "lab", "handbook", "notes", "html", "revise")
MODEL = "claude-opus-5-5"
PAIRS = 15
QUESTIONS = (
    ("does_what_was_asked", ("Which better does what the request asked (content, "
     "completeness, accuracy, the length and format asked for)?")),
    ("layout_and_readability", "Which is better laid out and easier to read?"),
)


def candidates(results: Path) -> list[dict]:
    found = []
    for folder in sorted(p for p in results.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((folder / "manifest.json").read_text())
        if m["model"] != MODEL or m["task"] not in HELD:
            continue
        last = m["steps"] > 1  # a session task is judged on its final output
        for other in ("baseline", "baseline-hinted"):
            for i in range(1, m["runs"] + 1):
                stems = [f"rupa-verify-{i}", f"{other}-{i}"]
                if last:
                    stems = [f"{s}.s{m['steps']}" for s in stems]
                if all((folder / "pages" / s).is_dir() for s in stems):
                    found.append({"folder": folder.name, "task": m["task"], "other": other,
                                  "run": i, "rupa": stems[0], "base": stems[1],
                                  "request": (folder / "steps" / f"{m['steps']}.txt").read_text()})
    return found


def make(results: Path, out: Path) -> None:
    rng = random.Random(0)
    chosen = rng.sample(candidates(results), PAIRS)
    out.mkdir(parents=True, exist_ok=True)
    key, sections = [], []
    for n, pair in enumerate(chosen, 1):
        rupa_a = rng.random() < 0.5
        a, b = (pair["rupa"], pair["base"]) if rupa_a else (pair["base"], pair["rupa"])
        cols = []
        for side, stem in (("A", a), ("B", b)):
            pages = sorted((results / pair["folder"] / "pages" / stem).glob("p-*.png"))
            imgs = []
            for k, page in enumerate(pages, 1):
                name = f"pair{n:02d}-{side}-{k:02d}.png"
                shutil.copy(page, out / name)
                imgs.append(f'<img src="{name}" alt="Document {side}, page {k}" loading="lazy">')
            cols.append(f'<div class="doc"><h3>Document {side} <small>{len(pages)} '
                        f'page{"s" * (len(pages) != 1)}</small></h3>{"".join(imgs)}</div>')
        qs = "".join(
            f'<fieldset><legend>{html.escape(text)}</legend>' + "".join(
                f'<label><input type="radio" name="p{n}-{qid}" value="{v}"> {v}</label>'
                for v in ("A", "B", "tie")) + "</fieldset>"
            for qid, text in QUESTIONS)
        sections.append(
            f'<section id="pair{n}"><h2>Pair {n} of {PAIRS}</h2>'
            f'<p class="req"><b>Request:</b> {html.escape(pair["request"])}</p>'
            f'<div class="questions">{qs}</div><div class="docs">{"".join(cols)}</div></section>')
        key.append({**{k: v for k, v in pair.items() if k != "request"}, "n": n,
                    "A": a, "B": b, "rupa_is": "A" if rupa_a else "B"})
    (out / "key.json").write_text(json.dumps(key, indent=2))
    (out / "index.html").write_text(PAGE.replace("{{N}}", str(PAIRS)).replace(
        "{{SECTIONS}}", "\n".join(sections)))
    print(f"human: {PAIRS} pairs in {out}/index.html (key in key.json; don't open it)")


def score(results: Path, out: Path, answers_file: Path) -> None:
    key = {k["n"]: k for k in json.loads((out / "key.json").read_text())}
    answers = json.loads(answers_file.read_text())
    agree = {q: [0, 0] for q, _ in QUESTIONS}
    rupa = {q: [0, 0, 0] for q, _ in QUESTIONS}
    for n, k in key.items():
        label = k["base"].replace(f"{k['other']}-", "", 1)
        llm_file = results / k["folder"] / "judge" / f"pair-{k['other']}-{label}.json"
        llm = json.loads(llm_file.read_text()) if llm_file.exists() else None
        for q, _ in QUESTIONS:
            mine = answers.get(f"p{n}-{q}")
            if mine is None:
                continue
            side = "rupa" if mine == k["rupa_is"] else "tie" if mine == "tie" else "base"
            rupa[q][("rupa", "base", "tie").index(side)] += 1
            if llm and llm.get("verdict"):
                theirs = llm["verdict"][q]
                llm_side = ("rupa" if theirs == llm["rupa_is"] else
                            "tie" if theirs == "tie" else "base")
                agree[q][0] += side == llm_side
                agree[q][1] += 1
    for q, _ in QUESTIONS:
        w, lo, t = rupa[q]
        a, n = agree[q]
        print(f"{q}: Rupa {w} wins, {lo} losses, {t} ties; agrees with the LLM judge "
              f"on {a} of {n}")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind Pair Judging</title>
<style>
:root { --bg: #fafaf8; --fg: #1d1d1b; --muted: #6b6b66; --line: #d9d8d2; --card: #fff;
        --accent: #1f5f8b; }
@media (prefers-color-scheme: dark) { :root { --bg: #161615; --fg: #ecebe6; --muted: #a3a29b;
        --line: #3a3a37; --card: #20201e; --accent: #7fb6dc; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
       font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 1400px; margin: 0 auto; padding: 24px 16px 120px; }
h1 { font-size: 1.6rem; margin: 0 0 8px; }
.intro { color: var(--muted); max-width: 70ch; }
section { border-top: 1px solid var(--line); padding: 24px 0; }
h2 { font-size: 1.2rem; margin: 0 0 8px; }
.req { max-width: 90ch; }
.questions { display: grid; gap: 8px; margin: 12px 0 16px; }
fieldset { border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px;
           background: var(--card); }
legend { padding: 0 4px; }
label { margin-right: 20px; white-space: nowrap; cursor: pointer; }
.docs { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 800px) { .docs { grid-template-columns: 1fr; } }
.doc h3 { margin: 0 0 8px; font-size: 1rem; }
.doc small { color: var(--muted); font-weight: normal; }
.doc img { display: block; width: 100%; height: auto; margin-bottom: 12px;
           border: 1px solid var(--line); background: #fff; }
#done { position: fixed; left: 0; right: 0; bottom: 0; background: var(--card);
        border-top: 1px solid var(--line); padding: 12px 16px; display: flex; gap: 12px;
        align-items: center; flex-wrap: wrap; }
#code { flex: 1; min-width: 200px; font: 12px ui-monospace, monospace; height: 3em; }
button { font: inherit; padding: 6px 14px; border-radius: 6px; border: 1px solid var(--accent);
         background: var(--accent); color: var(--bg); cursor: pointer; }
</style></head><body><main>
<h1>Blind pair judging</h1>
<p class="intro">{{N}} pairs. Each request was given to Claude Code set up in two
different ways, and the two results are shown as A and B in random order. For each
pair, answer both questions (a tie is fine). Judge whether each document works, not
whether you like its style. When you're done, copy the answer code at the bottom and
paste it to Claude. Your answers are kept in this browser if you reload.</p>
{{SECTIONS}}
</main>
<div id="done"><span id="count">0 answered</span>
<textarea id="code" readonly></textarea><button id="copy">Copy answer code</button></div>
<script>
const total = {{N}} * 2, store = "blind-pairs";
function answers() {
  const a = {};
  document.querySelectorAll("input[type=radio]:checked").forEach(i => a[i.name] = i.value);
  return a;
}
function update() {
  const a = answers();
  document.getElementById("count").textContent = Object.keys(a).length + " of " + total + " answered";
  document.getElementById("code").value = JSON.stringify(a);
  try { localStorage.setItem(store, JSON.stringify(a)); } catch (e) {}
}
try {
  const saved = JSON.parse(localStorage.getItem(store) || "{}");
  for (const [k, v] of Object.entries(saved)) {
    const el = document.querySelector(`input[name="${k}"][value="${v}"]`);
    if (el) el.checked = true;
  }
} catch (e) {}
document.addEventListener("change", update);
document.getElementById("copy").addEventListener("click", () => {
  const t = document.getElementById("code"); t.select();
  try { navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand("copy"); }
});
update();
</script></body></html>
"""

if __name__ == "__main__":
    if sys.argv[1:2] not in (["make"], ["score"]) or len(sys.argv) < 4 + (sys.argv[1] == "score"):
        sys.exit(__doc__)
    if sys.argv[1] == "make":
        make(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        score(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
