# Rupa

[![ci](https://github.com/VajraSarpa/rupa/actions/workflows/ci.yml/badge.svg)](https://github.com/VajraSarpa/rupa/actions/workflows/ci.yml)

**Claude writes the content. Rupa owns the form.**

Rupa is a command-line renderer and a Claude Code plugin. Claude writes plain
Markdown; Rupa turns it into a themed HTML page or PDF, checks the PDF with
code, and shows Claude page images only when something looks wrong. *Rūpa*
is Sanskrit for "form".

**Read the story:** [the case study](docs/dist/Rupa-Case-Study.pdf) covers why Rupa
exists, how it was measured, and what the measurements forced me to fix.

## Results

Claude Code with the plugin, against Claude Code on its own, on six document
tasks Rupa was never tuned on (Rupa v0.1.3, Claude Opus 5.5, five runs per
arm, medians, API list prices, 19–20 October 2026; hypotheses and pass rules
registered before the runs):

| Task | Claude Code alone | With Rupa | Time alone | Time with Rupa |
|---|---|---|---|---|
| One-page CV | $0.21 | $0.14 | 42 s | 24 s |
| Five-page lab report from data and a chart | $0.77 | $0.33 | 185 s | 76 s |
| Ten-page handbook | $0.51 | $0.39 | 140 s | 106 s |
| Two-page postmortem from notes | $0.30 | $0.16 | 65 s | 27 s |
| HTML explainer | $0.22 | $0.18 | 50 s | 36 s |
| Two-page report, then a revision | $1.05 | $0.44 | 142 s | 64 s |

- **42% cheaper** (0.58× the cost, 90% interval 0.55–0.63), and cheaper on
  all six tasks. Against Claude Code with a three-line hint on how to make a
  PDF, 38% cheaper.
- **71% less context over a working session.** Five documents in one
  session added 16,200 tokens to the conversation with Rupa and 55,300
  without, and cost $1.88 against $4.52 (v0.1.2, three runs per arm; every
  Rupa session stayed under 17,600, every baseline one over 50,400). Per
  document, Rupa adds about half the context.
- **Fewer API calls.** The same session took 13 model calls against 27.
  Per document it's 0.78× overall: half on the layout-heavy tasks (lab
  report 7 against 14), more on the simplest (an HTML page, 4 against 2,
  because Rupa always renders and then checks).
- **About 1.9× faster.**
- **The same to a human reader.** In my blind check of 15 random pairs, every
  pair tied on content, design and ease of reading. An LLM judge disagreed:
  it preferred Claude Code's document in most pairs, mainly for page balance
  and Rupa's plainer theme, so the pre-registered quality rule, which used
  that judge, fails. Both results are reported.

Context matters more than the bill suggests, especially on a Pro or Max plan
where there is no per-token bill. A document's cost is paid once, but the
context it adds stays: every later turn in the session re-reads it, and a
fuller window is compacted sooner. So the gap widens with each document, which
is why the session saves more than any single document.

Both savings come from one place: Claude stops writing and re-reading markup,
and Rupa answers with one status line instead of the document. The cost
saving is largest where Claude Code would otherwise iterate on its own
layout; the lab report
and the revision cost less than half. On the first benchmark's three tasks,
which Rupa was tuned against, the saving was 40–74%; the held-out figure is
the one to quote. Method, both judges and every run:
[the bench v2 report](bench/REPORT.md). Costs at volume:
[What Rupa Costs](docs/dist/Rupa-Cost-Analysis.pdf).

## How it works

![Rupa architecture: Claude writes Markdown through the rupa:render skill; the rupa CLI parses, renders and verifies](docs/rupa-architecture.svg)

1. **Claude writes Markdown** with a little frontmatter: title, subtitle,
   author, date, theme, contents and an optional page budget.
2. **`rupa` renders it** through a theme into HTML or PDF, offline. Given a
   page budget, it tightens type and spacing to fit, and if that isn't
   enough, it says how many lines to cut.
3. **`rupa verify` checks the PDF** with nine code checks and writes
   side-by-side sheets (the theme's reference page next to the rendered page)
   only for the pages a check flags.
4. **Claude reviews the flagged sheets** and fixes the Markdown, never the
   CSS. Rupa itself never calls a model.

## Install

Rupa needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and Pango for
WeasyPrint (`sudo apt install libpango-1.0-0 libpangoft2-1.0-0` on Debian or
Ubuntu, `sudo dnf install pango` on Fedora, `brew install pango` on macOS).

```bash
uv tool install git+https://github.com/VajraSarpa/rupa     # puts rupa on PATH
claude plugin marketplace add VajraSarpa/rupa
claude plugin install rupa@rupa                            # the Claude Code plugin
```

Then ask Claude Code for a PDF or an HTML page. The `rupa:render` skill takes
it from there.

## Use it directly

```bash
cat > report.md <<'EOF'
---
title: Quarterly Review
subtitle: What shipped and what's next
theme: cyan
toc: false
pages: 2
---

## Summary

Markdown in, **verified** PDF out.
EOF

rupa report.md -o report.pdf
# rupa: wrote report.pdf (pdf, 1 page, 8,629 bytes)
rupa verify report.pdf
# verify: 9/9 checks pass
```

Supported Markdown: CommonMark, tables, strikethrough, task lists, footnotes
and fenced code with syntax highlighting. Raw HTML is escaped, and images
must be PNG, JPEG, GIF, WebP or SVG files next to the Markdown (HTML output
embeds them).

## Themes

![The same cover in the default, cyan and cyan-dark themes](docs/img/themes.png)

| Theme | On screen (HTML) | PDF |
|---|---|---|
| `default` | Slate on white, light or dark with the system | Black on white |
| `cyan` | Deep navy, blueprint grid, one cyan accent | Black on white, cyan rules and pills |
| `cyan-dark` | Same as `cyan` | Navy pages, light ink |

A different look is always a theme change, never styling in the Markdown.
PDFs use bundled fonts (Inter, Hanken Grotesk, JetBrains Mono; SIL OFL 1.1),
so a PDF looks the same on every machine.

## Verification

`rupa verify` checks text colour, page size, page count, empty and sparse
pages, a short page before a figure, stranded headings and overflow, and reports exactly what and where
(`p1 table by 13pt`). It reads the theme from the PDF, so it compares against
the right reference pages without being told. A clean PDF gets no sheets, so
the visual review costs nothing when nothing is wrong. `wants.example.yaml`
lists every rule and its default.

## Limits

- **Claude Code only, for now.** Rupa is a local CLI plus a Claude Code
  plugin; it doesn't run in the Claude chat app.
- **HTML and PDF only.** No slides or DOCX yet.
- **Looks come from themes.** A new look means writing a theme in CSS.
- **Markdown limits.** No callouts; footnotes become endnotes in PDFs; bare
  URLs aren't clickable.
- **Short documents save the least.** Most of a short run is Claude Code
  starting a session; the one-page CV saved 7 cents.
- **Plainer pages.** Rupa keeps a theme's margins and breaks pages to keep
  blocks whole. An LLM judge prefers the baseline's denser, more styled
  pages; one person's blind check didn't.
- **The evidence has limits.** Five runs per arm on one model for the
  headline (on Sonnet 5.5 the saving was smaller, 0.67× the cost on v0.1.2),
  one person's tasks, written by Claude, and a human check of 15 pairs by one
  person.

## How the results were found

The benchmark (`bench/`) gives `claude -p` the same prompt in a fresh, empty
folder, across four arms: no plugin, Rupa render-only, Rupa with a sheet per
page type, and Rupa as shipped. The first benchmark found no saving. It took
page budgets, flagged-only review sheets and line-based cut hints to get to
a saving at all.

The wide-table task is the clearest example of measuring and then fixing.
Every first draft overflowed, and at first Rupa saved only 13%, because
Claude kept shrinking cell text. Claude Code alone turned the page to
landscape or shrank the type to 6.6pt. After the theme learned to set wide
tables in smaller type, every Rupa run fitted on its first render, 40%
cheaper:

![The same eleven-column table: Claude Code alone at 6.6pt with a header split mid-word, and Rupa at 7.5pt on the first render](docs/img/wide-table-before-after.png)

Those three tasks were the ones Rupa was tuned on, so a second benchmark
([bench v2](bench/REPORT.md)) tested six new tasks, against Claude Code
alone and with a hint, with user plugins switched off, on two models, with
quality judged by an LLM and by me, blind. It confirmed the cost saving and
found a plain bug: every image wider than the text column ran off the page,
and `rupa verify` passed it. v0.1.3 fixes that and three page-break faults;
the results above are from its rerun.

Every run is published as data: [`bench/data/`](bench/data/) (the first
benchmark, 101 runs), [`bench/data-v2/`](bench/data-v2/) (210 runs on v0.1.2)
and [`bench/data-v013/`](bench/data-v013/) (90 runs on v0.1.3), each with
turns, cost, time, tokens and context per run. The story of what changed
between runs is in the build guide ([PDF](docs/dist/Rupa-Plan-Guide-Tutorial.pdf),
section "Measuring the savings").

## Contract

The plugin and its evals depend on this. What each command reads, writes
and deletes, and which flags never change, is in
[docs/cli-contract.md](docs/cli-contract.md).

- **Input:** Markdown with optional YAML frontmatter, from a file or stdin.
- **`-o PATH`:** the output file; the format comes from the extension.
- **`pages: N` or `--pages N`:** a PDF page budget.
- **stdout:** one status line (or one JSON object with `--json`), never the
  document.
- **Exit codes:** `0` ok, `2` usage, `3` bad input, `4` render failure, `5`
  verify checks failed or a PDF still over its page budget.
- **Subcommands:** `rupa verify` and `rupa refs`. To render a Markdown file
  named `verify` or `refs`, write `./verify`.
- **Failure log:** every run that exits non-zero or crashes is appended to
  `~/.rupa/log.jsonl` (time, arguments, exit code, output, traceback if any,
  each clipped to 2,000 characters). Only you can read it, and past 1 MB it
  moves to `log.jsonl.1`. `RUPA_LOG=<path>` moves it; `RUPA_LOG=off` stops it.

## Repository

| Path | What it is |
|---|---|
| `src/rupa/` | The CLI: `rupa` (render), `rupa verify` (check a PDF), `rupa refs` (rebuild reference pages) |
| `src/rupa/themes/` | Theme CSS, a print layer per theme, and the bundled fonts |
| `src/rupa/references/` | The reference pages each theme is compared against |
| `plugin/` | The Claude Code plugin: one skill that renders, verifies and reviews |
| `plugin/evals/` | A `claude plugin eval` suite: does the skill trigger, render with Rupa and pass verify |
| `bench/` | The benchmarks (v1 four-arm, v2 held-out with judges), a fake `claude` for testing them without spending tokens, and every run as data |
| `docs/` | The build guide, cost analysis and architecture diagram, with their sources |

## Develop

```bash
uv sync
uv run pytest -q                   # 208 tests
uvx ruff check src tests
uv run rupa refs --theme <name>    # after any theme change; commit the PNGs
uv run python docs/build.py        # re-render the guide with Rupa
claude plugin validate ./plugin    # after any edit to plugin/
```

A golden-render test in CI renders a sample with every theme and fails if a
page drifts from its committed reference image.

## License

MIT
