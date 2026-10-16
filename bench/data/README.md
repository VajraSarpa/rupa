# Benchmark data

Every benchmark run behind Rupa's published numbers: 101 runs over twelve
results folders, 15–16 October 2026, on Claude Opus 5.5. The raw folders
(`bench/results/`) aren't in git; these two files are exported from them by
`bench/export.py`, so the numbers in the README, the cost analysis and the
case study can be checked here.

- **`runs.csv`:** one row per run.
- **`summary.csv`:** medians per folder and arm, with a `used_in` column naming
  the published numbers each one backs.

## How a run works

`bench/bench.sh` gives `claude -p` the task prompt (`bench/tasks/<task>.txt`)
in a fresh, empty folder, so no run can see this repository. Arms:

| Arm | What Claude has |
|---|---|
| `baseline` | Claude Code with no plugin: it writes the HTML, CSS or PDF code itself |
| `rupa` | The plugin with its verify section removed: render only |
| `rupa-pertype` | The plugin, with a review sheet for every page type |
| `rupa-verify` | The plugin as shipped: render, verify, and sheets for flagged pages only |
| `rupa-flagged` | The first folder's name for flagged-only sheets |

## Columns in `runs.csv`

| Column | Meaning |
|---|---|
| `folder`, `task`, `build` | The results folder, its task, and what the build was at the time |
| `arm`, `run` | Which arm, and which of its runs |
| `model` | Models the run used. Claude Code uses Haiku for small internal tasks alongside Opus, and `cost_usd` includes both |
| `turns`, `cost_usd`, `secs` | As Claude Code reported them; cost is at API list prices |
| `input`, `output`, `cache_read`, `cache_write` | Token totals for the run |
| `api_calls` | Distinct model calls in the transcript |
| `context_start`, `context_peak` | Tokens read by the first call and by the largest one |
| `context_added` | `context_peak − context_start`: what the document work added. This takes out Claude Code's own starting context, which differed between days (about 42,000 tokens on one, 29,000 on another) |
| `pdf` | Whether the run produced `report.pdf` |
| `verify_passed`, `verify_total`, `verify_failed` | The PDF checked with the current `rupa verify` rules |

## Reading it fairly

- **Three runs per arm, mostly.** Agent runs vary, so use the medians.
- **Builds changed between folders.** Compare arms within a folder, not
  across folders; the `build` column says what changed.
- **Verify is Rupa's own standard.** Baseline PDFs fail it partly for using
  coloured text and their own margins. They were readable.
- **Rupa documents hold fewer words at a fixed page count,** because Rupa keeps
  the theme's margins, so part of the saving is less writing.
- **The chat app wasn't measured.** These are Claude Code runs only.

## Rebuilding

The transcripts live in `~/.claude/projects/` on the machine that ran the
benchmark, so only that machine can re-export:

```bash
uv run python bench/export.py      # writes bench/data/runs.csv and summary.csv
```
