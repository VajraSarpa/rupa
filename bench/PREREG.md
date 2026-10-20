# Bench v2 pre-registration

Written 18 October 2026, before any paid bench v2 run. Committed together
with the task files it names; the commit hash is the registration. Changes
after the first paid run are listed at the end with the reason, never edited
in place.

## Question

Does Claude Code with the Rupa plugin (`v0.1.2`, as shipped) make documents
more cheaply than Claude Code alone, without making them worse, on tasks Rupa
was never tuned on?

## Arms

| Arm | What Claude has |
|---|---|
| `baseline` | Claude Code, no plugin |
| `baseline-hinted` | Claude Code, no plugin, and this `CLAUDE.md` in the work folder (fixed text, from `bench.sh`) |
| `rupa-verify` | Claude Code with the Rupa plugin as tagged |

The hint, verbatim:

> To make a PDF, write one HTML file with a print stylesheet (@page size and
> margins, body text 10-11pt).
> Print it with: google-chrome --headless=new --no-pdf-header-footer --print-to-pdf=OUT.pdf FILE.html
> Check the page count with pdfinfo OUT.pdf and adjust the HTML until it matches what was asked.

Every run: `claude -p` in a fresh empty folder (plus the task's `inputs/`),
`--setting-sources project --strict-mcp-config`, tools `Bash Write Read Edit
Skill`, model passed explicitly, 25-minute timeout per prompt, arms
interleaved in a seeded shuffle per run number.

## Tasks

Held out (written for v2, never used to tune Rupa): `cv` (1 page), `lab` (5
pages, supplied CSV and chart), `handbook` (10 pages), `notes` (2-page
postmortem from supplied notes), `html` (HTML page), `revise` (2-page report,
then a revision in the same session).

Seen (v1 tasks, Rupa was tuned on them): `report`, `guide`, `tight`, `wide`.

Session: `session`, five documents in one session.

Claude wrote these tasks and is also the agent under test. The task text is
fixed by this commit.

## Runs

| Set | Tasks | Arms | Runs per arm | Model |
|---|---|---|---|---|
| Pilot | `cv`, `notes` | all 3 | 1 | Opus 5.5 |
| Main | all 10 held-out and seen | all 3 | 5 | Opus 5.5 |
| Sonnet | 6 held-out | all 3 | 3 | Sonnet 5.5 |
| Session | `session` | `baseline`, `rupa-verify` | 3 | Opus 5.5 |

Pilot results are for finding harness bugs and are not analysed. If the pilot
shows a bug in the bench tooling, the tooling is fixed and the pilot rerun.
Rupa itself and the task text are not changed after this commit; a task
found to be impossible or ambiguous may be fixed before the main set only,
recorded below.

## Metrics

Per run, from its results folder: success (the requested file exists and is
non-empty), turns, `total_cost_usd` (list price; runs bill to a Claude plan),
wall time, context added (largest call context minus first), words.

Quality, the same for every arm:

1. **Mechanical** (`bench/quality.py`): page count as asked, no text outside
   the page, no text within 12 pt of an edge, smallest text at least 6 pt,
   required phrases, JSON block parses, numbered list, image present, HTML
   loads nothing remote. A check text extraction can't decide is unknown, not
   failed. Rupa's own `verify` is reported but not used for quality.
2. **Judge, per output**: Claude Sonnet 5.5 sees the task prompt, the task's
   checklist (`judge` in `checks.json`) and the output as page images (PDF at
   100 dpi; HTML printed to PDF by headless Chrome first), and rates each
   checklist item met / partly / not met, plus readability and layout 1–5.
   Requirement score: met = 1, partly = 0.5, not met = 0, averaged.
3. **Judge, pairwise**: for each task and run number i, `rupa-verify` run i
   against `baseline` run i, and against `baseline-hinted` run i, shown as A
   and B in random order with the task prompt. The judge says which better
   does what was asked, and which is better laid out and easier to read; a tie
   is allowed. Rupa's look is recognisable, so this is only partly blind.
4. **Human**: Vajra judges 15 pairs drawn at random (seed 0) from the Opus
   held-out pairs, the same two questions, blind to arm. His agreement with
   the LLM judge is reported.

## Hypotheses and pass rules

Primary set: Opus, the six held-out tasks. Each rule is tested against
`baseline` and `baseline-hinted` separately.

- **H1, cost.** Cost per success (all runs' cost over successful runs) is
  lower for `rupa-verify` on at least 4 of 6 tasks, and the bootstrap 90%
  interval of the geometric mean, across tasks, of the per-task ratio of
  median cost (`rupa-verify` / baseline) lies below 1. Bootstrap: resample
  runs within task and arm, 10,000 times, seed 0. Failed runs' costs are
  included through cost per success.
- **H2, quality not worse.** Pooled judge requirement score for
  `rupa-verify` is no more than 0.05 below the baseline's, and `rupa-verify`
  does not lose the pairwise "does what was asked" question on more than
  half the decided pairs.
- **H3, reliability.** `rupa-verify` has no more failed runs than the
  baseline, plus one, on any task.

The claim "Rupa makes documents more cheaply without making them worse"
holds against a baseline if H1, H2 and H3 all hold against it. Anything else
is reported as it came out, including a pass against one baseline and not
the other.

Reported without a pass rule: the same on seen tasks (how much of v1's gain
came from tuning: compare the held-out and seen cost ratios), Sonnet, the
session (cost and context at the end of five documents), turns, time, context,
words, and Rupa's `verify` result for every PDF.

## Exclusions and reruns

A run is rerun once, and the rerun is used, only when it failed for a reason
outside the agent: a usage-limit or API error in the result event
(`is_error` with an API status), or a contaminated baseline (the Rupa skill
loaded or `rupa` ran). Each such rerun is listed in the report. Every other
failure counts against its arm.

## Changes after registration

Pilot, 18 October 2026 (`cv`, `notes`; not analysed, kept in
`bench/results/pilot/`). Tooling only; no task, rule or Rupa change:

1. The arm order was seeded by run number alone, so every task got the same
   order. The seed now includes the task name.
2. The judge's folder held only page images, so checklist items that say
   "check against notes.txt" or "data.csv" couldn't be checked. The task's
   input files are now copied in and named in the prompt.
3. Main runs go from a git worktree of the committed tooling, so editing the
   repo can't change a script while it runs (it broke the pilot's last lines).

Seen in the pilot, recorded and not fixed (Rupa is frozen): in `notes`, a
table split across a page break left one row and a repeated header at the
top of page 2, and `rupa verify` passed it.

## Addendum: v0.1.3 rerun (19 October 2026, before any v0.1.3 run)

Bench v2 found four layout faults in Rupa. Four fixes were then made, each
test first, and tagged `v0.1.3`:

1. Images are never wider than the text column (`max-width: 100%`).
2. `rupa verify`'s `overflow` check covers images.
3. A table split across pages keeps at least two body rows on each side.
4. Images are at most 3 in tall, and a new `figure-gap` verify check flags a
   page under 70% full before a figure that opens the next page.

**Question.** Does `v0.1.3` close the layout gap on held-out tasks, and does
the cost saving still hold?

**Runs.** Held-out tasks only (`cv`, `lab`, `handbook`, `notes`, `html`,
`revise`), all three arms, 5 runs per arm, Opus 5.5, `FREEZE_TAG=v0.1.3`,
`SEED=v013`. That is 90 runs. Same task text, hint, flags, timeout and
interleaving as above. No Sonnet, seen or session sets.

**Tooling change, applied to both versions.** `in_bounds` now fails an image
whose box lies outside the page, as well as text (bench v2 missed the clipped
lab chart because the check read only text). The v0.1.2 results are rescored
with the new check, and both versions are compared on it. Under it, v0.1.2
fails 8 PDFs, all `rupa-verify` lab reports.

**Rules.** H1–H3 and the exclusion rules above apply unchanged, against each
baseline. The layout comparison with v0.1.2 has no pass rule. Report
`rupa-verify`'s pairwise layout wins, losses and ties per task, next to
v0.1.2's held-out Opus figures (14 / 56 / 0, 70 pairs against both baselines). Report also the per-output
layout score, and the count of pages flagged by `figure-gap` in every arm.
A smaller layout loss count is described as a narrower gap only if it holds
on more than one task. The LLM judge was harsher than Vajra in v2, so a human
check of 15 pairs (seed 0, blind) is offered to Vajra and reported if he does
it.
