# Rupa

A renderer layer for Claude Code. Claude writes Markdown; Rupa owns the form
and turns it into a styled HTML page or PDF, then helps check the result.

*Rūpa* is Sanskrit for "form".

![Rupa architecture: Claude writes Markdown through the rupa:render skill; the rupa CLI parses, renders and verifies](docs/rupa-architecture.svg)

```bash
uv tool install .
echo "# Hello" | rupa -o hello.pdf
# rupa: wrote hello.pdf (pdf, 1 page, 9,812 bytes)
rupa verify hello.pdf
# verify: 8/8 checks pass
```

## Why

When Claude Code makes a document by hand, it writes every tag and CSS rule,
hunts for a PDF tool, and debugs the render. Each of those is a turn, and every
turn re-reads the whole conversation. Rupa takes the form work out of the loop:
Claude writes content, Rupa applies a tested theme and prints one status line.

## What's here

| Path | What it is |
|---|---|
| `src/rupa/` | The CLI: `rupa` (render), `rupa verify` (check a PDF), `rupa refs` (rebuild reference pages) |
| `src/rupa/themes/` | Theme CSS: `default`, `cyan` (dark screen, light PDF) and `cyan-dark` (dark PDF), plus a print layer per theme. Light themes print solid black text. `fonts/` bundles Inter, Hanken Grotesk and JetBrains Mono (SIL OFL 1.1), so a PDF looks the same on any machine |
| `src/rupa/references/` | Reference pages each theme is visually compared against |
| `plugin/` | Claude Code plugin: one skill that renders, verifies and reviews |
| `plugin/evals/` | `claude plugin eval` suite: does the skill trigger, render with rupa, and pass verify |
| `bench/` | Four-arm benchmark (baseline, Rupa render-only, Rupa + per-type review, Rupa as shipped) and a fake `claude` for testing it |
| `docs/` | Plan, guide and tutorial: Markdown source, build script, rendered PDF and HTML |
| `wants.example.yaml` | Every verification rule, with its default |

## Contract

- **stdin or a file:** Markdown with optional YAML frontmatter
- **`-o PATH`:** the rendered file, format from the extension
- **`pages: N` or `--pages N`:** a PDF page budget. Rupa fits it by dropping
  the contents list and tightening type; if it still can't, it says how many
  words to cut
- **stdout:** one status line, never the document
- **exit codes:** `0` ok, `2` usage, `3` bad input, `4` render failure, `5` verify checks failed or a PDF still over its page budget
- **failure log:** every run that exits non-zero or crashes is appended to
  `~/.rupa/log.jsonl` (time, argv, exit code, output, traceback if any).
  `RUPA_LOG=<path>` moves it; `RUPA_LOG=off` stops it

## Verification

`rupa verify` runs code checks on the PDF (color, page size, page count, empty
or sparse pages, stranded headings, overflow). It also writes side-by-side
sheets, reference page | rendered page, for every page a check flags, so a
clean PDF gets none (`--sample per-type` adds one page of each type). The plugin's skill has Claude review those sheets against a rubric
and fix the Markdown. Rupa never calls a model itself.

## Use it from Claude Code

```bash
uv tool install .                  # puts rupa on PATH
claude plugin validate ./plugin
claude --plugin-dir ./plugin
```

Then ask for a PDF. The `rupa:render` skill takes it from there.

## Develop

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and Pango for WeasyPrint
(`sudo apt install libpango-1.0-0 libpangoft2-1.0-0`, or `brew install pango`).

```bash
uv sync
uv run pytest -q                   # 113 tests
uvx ruff check src tests
uv run rupa refs                   # after any theme change; commit the PNGs
uv run python docs/build.py        # re-render the guide with Rupa
```

## Status

Working prototype. Benchmark (2026-10-16, three runs per arm on Opus 5.5, a
two-page report): the plugin as shipped took 7 turns and $0.29 per run
against baseline's 13 turns and $0.52, which is 45% cheaper, and every run
fitted 2 pages on its first render. Rupa's reports carry fewer words than
baseline's (about 720 against 1,180), because it keeps the theme's margins.

On a harder task (a 3-page guide with a five-column table, CLI and JSON policy) the
gap widens. In the latest run, after over-budget hints moved from words to
lines, the shipped plugin took 6 turns and $0.31 against baseline's 23 turns
and $1.19, and 7 of 9 Rupa runs fitted on their first render. Baseline varied
between $0.85 and $1.19 across three guide runs, so read the saving as
roughly 60–75%.

A table too wide for the page (eleven required columns) at first overflowed
in every Rupa draft, and the shipped plugin saved only 13% while it split or
tightened the table. The theme now sets tables of 9 or more columns in
smaller type: every run then fitted on its first render, and the shipped
plugin took 6 turns and $0.33 against baseline's 11 turns and $0.54.

The first benchmark, before page budgets and flagged-only sampling, found no
saving. See the guide's "Measuring the savings" section for every run.

For cost per document against Claude Code alone and Claude in the chat app,
with projections at volume, see [What Rupa Costs](docs/dist/Rupa-Cost-Analysis.pdf)
(source: [docs/cost-analysis.md](docs/cost-analysis.md)).

## License

MIT
