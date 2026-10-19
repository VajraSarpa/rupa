# Bench v2 plan

A more thorough rerun of the Rupa benchmark: held-out tasks, a stronger
baseline, more runs, a second model, failed runs counted, and quality judged
by something other than Rupa's own `verify`. Started 18 October 2026 on branch
`bench-v2`. Vajra asked Claude to build the tooling and run the whole thing.

Runs bill to Vajra's Claude plan (no `ANTHROPIC_API_KEY` is set), so
`cost_usd` is Claude Code's list-price figure, not money spent.

## Why v1 needs redoing

1. Tuned on the test set: every v1 task drove a fix and was re-measured.
2. Quality was Rupa's own `verify`, which baseline fails on house rules.
3. n=3, Opus only.
4. Arms ran in blocks, not interleaved.
5. Runs without a PDF were dropped from the medians.
6. The wide-table 40% compares two results folders.
7. **Found while planning Phase 0:** a plain `claude -p` now loads every
   user-installed plugin, including `rupa@rupa` (installed 2026-10-16 14:02
   UTC), plus 116 skills and 39 MCP servers. A v2 baseline run without
   isolation would have had the Rupa skill. The v1 runs all predate the
   install (last folder 13:41 UTC), but they did load whatever user skills
   and MCP servers existed then, equally in every arm.

## Phase 0: freeze and fix the tooling (no spend)

**Freeze.** Rupa's `src/`, `plugin/`, `pyproject.toml` and `uv.lock` stay at
`v0.1.2`. `bench.sh` refuses to run if they differ from the tag, or if
`rupa --version` isn't `0.1.2`. The plugin each run loads is a copy exported
from the tag into the results folder, not the working tree. Any Rupa change
means a new tag and a fresh benchmark.

**Isolation.** Every run is
`claude -p --setting-sources project --strict-mcp-config`: no user plugins,
skills or MCP servers, only Claude Code's built-ins (22 skills, 28 tools).
Checked by probe on 18 Oct: `--plugin-dir` still loads Rupa, and a
`CLAUDE.md` in the work folder is still read. Each run records its `init`
event; the export flags any baseline run whose init lists a Rupa skill or
whose tool calls run `rupa`.

**`bench.sh`:**

- Tasks become folders: `bench/tasks/<name>/prompt.txt`, `output` (the file
  the task asks for; default `report.pdf`), optional `inputs/` copied into the
  work folder, `checks.json` for `quality.py`. The four v1 tasks move over
  unchanged.
- Arms: `baseline`, `baseline-hinted` (work folder gets a three-line
  `CLAUDE.md`: write Markdown, convert with headless Chrome, check the page
  count), `rupa-verify`. `rupa` and `rupa-pertype` stay available through
  `ARMS=`.
- Interleaved: for each run number, the arms go in a shuffled order. The
  order and start time of every run go in `manifest.jsonl`.
- `--output-format stream-json --verbose`: the whole stream is kept as
  `<arm>-<i>.jsonl`, and the final result object as `<arm>-<i>.json` (same
  shape as v1). The results folder no longer depends on `~/.claude/projects`.
- The work folder is kept as `<arm>-<i>.work/` (for the hand-written-markup
  and contamination checks).
- `manifest.json`: Claude Code version, Rupa version and tag, bench commit,
  model, task, arms, runs, flags.
- Model is always passed explicitly (`MODEL`, default `claude-opus-5-5`).
- Each run has a 25-minute timeout; a timeout is a failed run.

**`bench/session.sh`:** the multi-document session. One `claude -p`, then
four `--resume` calls, each asking for the next document. Same isolation and
recording.

**`bench/export.py`:** reads v2 folders (task and build from the manifest,
context from the saved stream); per arm: runs, successes, success rate,
medians with IQR, and cost per successful document counting failed runs'
cost. v1 folders still export as before. v2 output goes to `bench/data-v2/`;
the published v1 data stays as it is.

**`bench/quality.py`:** checks every output the same way in every arm,
without Rupa's rules:

- page count against the task's budget;
- characters outside the page box; smallest font size (fails under 7 pt);
- word count;
- per-task requirements from `checks.json`: required phrases, a table with
  at least N rows and M columns, a JSON block that parses with at least N
  lines, a numbered list, an image present;
- HTML: file exists, required phrases, no external resources.

**Old-data audit:** scan the v1 baseline transcripts for any `rupa` call.

**Tests:** `bench/fake/claude` learns stream-json and writes whatever output
the prompt names; `tests/test_bench.py` runs `bench.sh` and `export.py` end
to end with the fake, and checks `quality.py` against PDFs rendered in the
test. Full suite and ruff stay green.

**Done when:** a fake run of every task and arm produces a complete results
folder, export and quality report; the freeze and isolation checks refuse
when they should; tests pass.

## Phase 1: held-out tasks

Written and committed before the first paid run, never used to tune Rupa:
one-page CV; five-page lab report with a supplied PNG chart; ten-page
handbook; convert supplied notes into a document; an HTML page; revise an
existing report (add a section, keep 2 pages). Claude writes these tasks
and is also the agent under test, so the task text is committed in a separate
commit before any paid run, and its hash is recorded in `PREREG.md`.

## Phase 2: arms

`baseline`, `baseline-hinted`, `rupa-verify`, as above.

## Phase 3: pre-register, then run

`bench/PREREG.md` before any paid run: hypotheses, metrics, pass rule
(rupa-verify cheaper than both baselines on at least 4 of 6 held-out tasks,
bootstrap 90% CI on the cost ratio excluding 1, requirements score no worse).

| Step | Runs | List-price est. |
|---|---|---|
| Pilot: 2 held-out tasks × 3 arms × 1, Opus | 6 | ~$4 |
| Main: 10 tasks × 3 arms × 5, Opus | 150 | ~$80 |
| Sonnet: 6 held-out tasks × 3 arms × 3 | 54 | ~$15 |
| Session: 5 documents in one session, baseline vs rupa-verify × 3 | 6 sessions | ~$12 |

## Phase 4: quality

`quality.py` on every output; blind pairwise judging of page images by an
LLM judge with a fixed rubric, and by Vajra on 15 random pairs.

## Phase 5: report

Per task and arm: success rate, median cost and IQR, turns, time, context
added, requirements score, judge preference; seen and held-out separately.
Update the README, cost analysis and case study even where numbers get worse,
and list the v1 claims this supersedes.
