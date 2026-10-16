---
title: Rupa
subtitle: Plan, guide, and tutorial for a renderer layer for Claude Code
author: Vajra Sarpa
date: October 15, 2026
---

## About this document

Rupa (Sanskrit *rūpa*, "form") is a small command-line renderer. Claude writes content as Markdown; Rupa owns the form, turning that Markdown into a styled HTML page or PDF. A thin Claude Code plugin teaches Claude to use it.

The document has three parts plus a short note on presenting the build:

- **Part 1, Plan:** what to build, why, the decisions, milestones and risks.
- **Part 2, Guide:** the reference for how Rupa works once it exists.
- **Part 3, Tutorial:** build it step by step, from an empty folder to a tested CLI, a validated plugin, a verification loop and a benchmark.

Everything in Part 3 was built and run before this was written: 40 tests pass, `claude plugin validate` passes, and Claude Code loads the skill and uses it to render and verify a PDF on its own. This document was rendered by that prototype from one Markdown file, then checked with `rupa verify` and a visual review of its sample pages. The appendix records what that review found.

# Part 1: Plan

## The problem

When Claude Code produces an HTML page or PDF, it writes the markup itself: every tag, every CSS rule, or a script that builds the PDF. Four costs follow.

- **Turns.** Finding a PDF tool, installing it, rendering, and debugging the result each take a turn, and every turn re-reads the whole conversation from cache. In the one run measured during the build, cache reads were about 99% of the tokens processed, so turn count is what drives cost.
- **Output tokens.** Markup and styling are a large share of what Claude writes. They are the slowest tokens, but a small share of the total.
- **Revision cost.** A one-line content fix often regenerates the whole file, styling included.
- **Inconsistency.** Each document is styled from scratch, so two reports never look quite the same, and render bugs are fixed in one file at a time.

## The idea

Split content from form. Claude emits compact Markdown with a few frontmatter keys. Rupa, a deterministic and tested program, applies the theme and produces the file. Rupa prints one status line, so Claude doesn't read the rendered output back by accident.

Then check the result where it matters, because people read these documents and people like pretty things. Rupa runs code checks on the PDF and prepares a small set of page images, each next to the matching page of the theme's reference. Claude looks at those deliberately. Tokens are saved on generation and spent on review.

| Without Rupa | With Rupa |
|---|---|
| Claude writes HTML, CSS, PDF code | Claude writes Markdown |
| Styling re-emitted on every revision | Styling lives in Rupa themes |
| Claude re-reads the whole output to check it, or doesn't check | Code checks every page; Claude looks at a few sampled pages next to a reference |
| Every document styled ad hoc | One theme, applied the same way every time |

## Goals and non-goals

**Goals**

1. Markdown plus frontmatter in, HTML or PDF out, from stdin or a file.
2. stdout carries one status line (or one JSON object), never the document.
3. Clear exit codes so Claude can fix input without guessing.
4. PDF body text is solid black (#000000, full opacity).
5. A Claude Code plugin under about 30 lines of instructions, with no always-on MCP tool definitions.
6. Every PDF verified twice: code checks for what can be measured, and a visual review against the theme's reference pages for what can't.
7. A repeatable benchmark that measures turns and cost per finished document instead of assuming them.

**Non-goals for v1**

- A layout language. If Markdown cannot express it, it waits for a later version.
- DOCX or PPTX output. They can be added as new targets behind the same contract.
- Remote assets. Images must be relative paths or `data:image` URIs, so neither HTML nor PDF fetches from the network.

## Architecture

The pipeline is linear and each stage has one job.

```text
Markdown + frontmatter   (stdin or a file)
        │
        ▼
parse()                  document.py   → Document(meta, body_html, headings)
        │
        ▼
to_html()                render.py + themes/*.css
        │
        ├──► .html file
        └──► to_pdf()    WeasyPrint    → .pdf file
                                            │
                                            ▼
verify()                 verify.py     → checks + sheets + verify.json
        │
        ▼
Claude reads the sheets, judges them against the rubric, fixes the Markdown

stdout: one status line          exit code: 0 / 2 / 3 / 4 / 5
```

| Module | Responsibility | Knows about styling? |
|---|---|---|
| `document.py` | Parse frontmatter, Markdown, headings | No |
| `render.py` | HTML template, theme CSS, PDF | Yes, and only here |
| `themes/*.css` | All visual decisions | Yes |
| `verify.py` | PDF checks, page types, review sheets | Reads the result, never styles it |
| `references/` | Reference pages for each theme and page type | They are the theme's picture of itself |
| `cli.py` | Arguments, I/O, status line, exit codes | No |
| `plugin/` | Teach Claude the contract | No |

## Key decisions

| Decision | Choice | Why | Rejected |
|---|---|---|---|
| Interface | CLI over stdin/stdout | Works in Claude Code, CI, scripts and any harness; zero context cost until called | MCP server: tool schemas sit in context every turn |
| Input format | Markdown + YAML frontmatter | Claude writes it fluently; few tokens; no schema to teach | Custom JSON schema: more prompt overhead and more retries |
| PDF engine | WeasyPrint | Pure Python install, real CSS paged media (page numbers, running titles) | Headless Chrome: heavy dependency; LaTeX: a second styling system |
| Markdown parser | markdown-it-py | CommonMark compliant, plugin system, token stream for headings | Python-Markdown: weaker spec compliance |
| CLI library | argparse | No dependency, enough for six flags | Typer/Click: nice, not needed yet |
| Raw HTML in input | Escaped | Keeps Claude from smuggling styling back in; safer output | Pass-through |
| Plugin form | One skill + one hook | Skill body loads only when triggered | Many slash commands |
| Verification | Code checks, then vision on sampled pages beside reference pages | Code is exact and free; vision judges what code can't. Sampling by page type keeps the cost tied to variety, not length | Vision on every page (~85k tokens for 31 pages); pixel diffs (content always differs from the reference) |
| Who looks at the images | Claude, through the skill | Rupa stays offline with no API key; Claude is already a vision model | Rupa calling a model API itself |

## Milestones

Estimates assume evenings and weekends.

| # | Milestone | Done when | Estimate |
|---|---|---|---|
| M0 | Scaffold | `uv sync` and an empty test run pass | 1 hour |
| M1 | Parser | Document model and 8 parser tests pass | 2–3 hours |
| M2 | Renderer | HTML and PDF from a sample; PDF text forced black | 3–4 hours |
| M3 | CLI contract | Status line, `--json`, exit codes, CLI tests pass | 2 hours |
| M4 | Plugin | `claude plugin validate` passes; skill loads with `--plugin-dir` | 1–2 hours |
| M5 | Verify | `rupa verify` checks and sheets; reference pages built; skill runs the review loop | 4–6 hours |
| M6 | Measure | Pilot of one run per arm, then three runs per arm; medians recorded | 2 hours plus about $2–6 of API use |
| M7 | Ship | CI green on GitHub Actions; `uv tool install` from the repo works | 1–2 hours |

## Success metrics

- **Primary:** median turns and median cost (`total_cost_usd`) per finished document, Rupa against baseline. Turns come first because each one re-reads the whole context, so fewer turns is where most of the saving should come from. Report the numbers you get, whichever way they go.
- **Secondary:** median cache reads and output tokens, and the success rate (runs that produced the PDF).
- **Verification overhead:** the difference between the `rupa` and `rupa-verify` arms, which is what the visual review costs per document.
- **Quality:** all tests green; the same input renders the same output every time; every delivered PDF passes `rupa verify` and a visual review with no open failures.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Savings smaller than expected | Medium | Medium | Pilot in M6 before investing in themes; judge on turns and cost, not output tokens alone |
| Vision verdicts vary between runs | Medium | Medium | Fixed rubric, one structured verdict per sheet, code checks for anything measurable, two fix rounds at most |
| Code checks misread a page (page type, fill) | Medium | Low | Unit tests on synthetic pages; flagged pages always go to the visual review, so a wrong flag costs one sheet |
| Claude ignores the skill and hand-writes HTML | Medium | High | Short, direct skill description; check with the benchmark transcripts |
| WeasyPrint system libraries missing on a machine | Medium | Low | Exit code 4 with a clear message; install notes in the tutorial; CI installs them |
| Markdown can't express a layout the user wants | High over time | Medium | Add themes and small, explicit extensions; never accept raw HTML |
| Library API changes (this happened during the build: WeasyPrint 70 replaced its URL fetcher API) | Medium | Low | Pin minimum versions; tests cover the behavior, not the library call |

# Part 2: Guide

## The contract

Rupa has one contract, and the plugin, tests and benchmark all depend on it.

| Channel | Carries |
|---|---|
| stdin or file argument | Markdown with optional YAML frontmatter |
| `-o PATH` | The rendered file. Format comes from the extension, or `--to html` / `--to pdf` |
| stdout | One status line, or one JSON object with `--json`. Never the document |
| stderr | One error line on failure |
| exit code | `0` ok, `2` usage, `3` bad input, `4` render failure, `5` verify checks failed |

Two subcommands follow the same rules:

| Command | Does | Prints |
|---|---|---|
| `rupa verify OUT.pdf [--wants F]` | Runs the checks, writes sheets and `verify.json` | One line: checks passed, failures, sheet count |
| `rupa refs [--theme T]` | Rebuilds a theme's reference pages from the bundled sample | One line: which sample page became each reference |

Example:

```bash
$ rupa notes.md -o out/notes.pdf
rupa: wrote out/notes.pdf (pdf, 3 pages, 48,211 bytes)

$ rupa notes.md -o out/notes.pdf --json
{"ok": true, "path": "out/notes.pdf", "format": "pdf", "pages": 3, "bytes": 48211}
```

## Input format

Frontmatter is optional. Only these keys are accepted; anything else is exit code 3, so typos fail loudly instead of being ignored.

| Key | Type | Effect |
|---|---|---|
| `title` | string | Cover title and PDF running footer. Defaults to the first heading |
| `subtitle` | string | Line under the title |
| `author` | string | Byline |
| `date` | string | Byline, after the author |
| `theme` | string | Theme name. Defaults to `default`; `--theme` overrides it |
| `toc` | bool | Table of contents from `#` and `##` headings. Defaults to true |

Body conventions:

- `#` is a part. In PDF each part starts a new page.
- `##` is a section, `###` a subsection. Sections get anchors automatically.
- Fenced code blocks take a language tag for highlighting.
- Tables use GitHub pipe syntax.
- Raw HTML is escaped and shown as text.
- Images must be relative paths next to the Markdown file, or `data:image` URIs. A URL or absolute path is bad input (exit code 3); a missing file, or one outside the Markdown file's folder, fails the PDF render (exit code 4).

## Themes

A theme is one CSS file in `src/rupa/themes/`. The PDF target appends `print.css` on top of it, which sets the page size, margins, footer, page breaks, and forces all text to solid black:

```css
body, p, li, td, th, h1, h2, h3, h4, blockquote, code, pre,
.subtitle, .byline, .toc a, a {
  color: #000000 !important;
  opacity: 1 !important;
}
.hl * { color: #000000 !important; font-style: normal !important; }
```

The cyan accent survives only on rules and borders, never on text. Syntax highlighting is turned off in PDF for the same reason.

Code blocks use `white-space: pre-wrap` and nothing else. WeasyPrint treats `word-wrap: break-word` as permission to break anywhere, which split `solid` into `s` and `olid` in an earlier render of this document. The visual review caught it; the code checks couldn't.

To add a theme, copy `default.css` to `newname.css`, change the variables at the top, add the name to `THEMES` in `render.py`, and run `rupa refs --theme newname` to build its reference pages.

## Verification

Rendering proves the file exists. Verification checks that it's right, in two tiers.

**Tier 1: code checks.** `rupa verify` reads the PDF with pdfplumber and checks what can be measured exactly. Each check is free, repeatable and reports page numbers.

| Check | Fails when |
|---|---|
| `text-color` | Any character isn't the wanted color (#000000 by default) |
| `page-size` | A page isn't Letter (or A4, if the wants file says so) |
| `max-pages` | The document is longer than the limit |
| `blank-page` | A page has no text |
| `near-empty` | A page is under 20% full (cover and last page exempt) |
| `sparse` | A page is under 40% full and the next page doesn't start a new part |
| `heading-at-bottom` | A heading is the last line on a page |
| `overflow` | Text runs past the side margins |

**Tier 2: visual review.** Code can't tell whether a page looks right. For that, `rupa verify` classifies each page as cover, prose, table or code. It then writes a sheet image for every flagged page plus one page of each type, with the theme's reference page on the left and the rendered page on the right. Claude opens those sheets and judges each one against a fixed rubric: hierarchy, spacing, overflow, page balance and style.

### The wants file

A `wants.yaml` holds what a finished PDF must satisfy. Every key is optional, unknown keys are an error, and `wants.example.yaml` in the repo spells out the defaults. A project that needs A4 and a 10-page limit writes two lines:

```yaml
page_size: a4
max_pages: 10
```

### Reference pages

A theme's reference pages are its picture of itself. `rupa refs` renders a bundled sample document with the theme and saves the most typical page of each type as a PNG inside the package. Rebuild them whenever the theme's CSS changes, and commit them with it. A sheet without a reference still shows the page, labeled so.

### What it costs

An image costs roughly its width times height divided by 750 in input tokens. A sheet at the default 90 DPI is about 1,530 × 1,020 pixels, or about 2,000 tokens.

| How Claude reviews the 31-page version of this document | Images | Input tokens, approx. |
|---|---|---|
| Every page at full resolution | 31 | 85,000 |
| `rupa verify`: flagged pages plus one per type | 5 | 10,000 |
| Code checks only | 0 | under 100 |

The sampled review scales with how varied the document is, not how long it is. That is the right place to spend tokens: the reader sees the result.

### The loop

The skill tells Claude to render, verify, open the sheets, and write one verdict per sheet. Claude fixes failures in the Markdown only: split a wide table, shorten a code line, move content around an awkward break. Then it renders and verifies again, at most twice. A problem that can only be fixed in CSS is reported as a theme issue rather than patched, so one document's quirks don't leak into the theme.

## Plugin anatomy

The plugin is deliberately small. Claude Code only needs to know that Rupa exists and how to call it.

```text
plugin/
├── .claude-plugin/
│   └── plugin.json        # name, version, description, author
├── skills/
│   └── render/
│       └── SKILL.md       # the whole instruction set, ~40 lines
└── hooks/
    └── hooks.json         # SessionStart: warn if rupa is not on PATH
```

What each part costs in context:

| Component | When it loads | Cost |
|---|---|---|
| Skill name and description | Every session | One line |
| Skill body | Only when the skill is triggered | About 40 lines |
| Review sheets | Only when Claude opens them during verification | About 2,000 tokens each |
| SessionStart hook | Session start | Prints nothing if `rupa` is installed |
| MCP server | Not used | Would be every turn |

Claude Code namespaces plugin components under the plugin name, so the skill appears as `rupa:render`.

Two alternatives you may want later:

- **`bin/` directory.** Files in a plugin's `bin/` are put on the Bash tool's PATH while the plugin is enabled, so you could ship a `rupa` wrapper inside the plugin. The catch: claude.ai and Cowork don't install a plugin that has a top-level `bin/` directory, so this limits where the plugin can be used. Keep the CLI installed separately with `uv tool install` unless you only care about Claude Code.
- **MCP server.** Worth it only if Rupa grows state or a live preview. Until then it adds per-turn context for nothing.

## Token discipline

The savings come from what Claude does not do. The skill enforces four rules:

1. Write Markdown, not markup.
2. Never put styling in the content. A different look is a theme change.
3. Read the status line, not the output file. Look at pages only through the review sheets, where looking is the point.
4. On failure, read the one stderr line and fix the input.

The fourth rule depends on Rupa's errors being specific. "unknown frontmatter keys: ['colour']" lets Claude fix the problem in one edit. A stack trace would cost a turn and a lot of tokens.

## Measuring the savings

### Where the cost goes

One run from the build, not a benchmark: asked for a one-page PDF summary of the six Well-Architected pillars, Claude Code with the plugin rendered, ran `rupa verify`, opened the sheet, and fixed the Markdown once to get the document to one page. No HTML or CSS was written by hand.

| Measure | Value |
|---|---|
| Turns | 16 |
| Cache reads | 636,178 tokens |
| Cache writes | 57,643 tokens |
| Uncached input | 28 tokens |
| Output | 3,651 tokens |
| Total cost | $0.33 |

Output was about half a percent of the tokens processed. Every turn re-reads the conversation, so cost tracks turns. That changes what Rupa should be judged on: not mainly smaller output, but fewer turns. No hunting for a PDF tool, no render debugging, and one-line errors that are fixed in one edit.

### Three arms

`bench/bench.sh` runs the same task in three arms through Claude Code's print mode (`claude -p ... --output-format json`):

| Arm | Setup | Answers |
|---|---|---|
| `baseline` | No plugin | What it costs today |
| `rupa` | Plugin with the skill's Verify section removed | What rendering through Rupa saves |
| `rupa-verify` | Plugin as shipped | What the visual review adds back |

The render-only arm uses a copy of the plugin made at run time, so all three arms get exactly the same prompt. Each run starts in a fresh empty directory, so no arm can read the Rupa repo. `bench/summarize.py` prints one row per run and the medians per arm, with turns and cache reads first, then a line comparing each Rupa arm to the baseline.

### What it will cost

Estimates on the default model, from the run above:

| Arm | Per run, approx. |
|---|---|
| `baseline` | $0.40–1.00; wide, because it depends on whether Claude detours to find and install a PDF tool |
| `rupa` | $0.25–0.40 |
| `rupa-verify` | $0.30–0.50 |

A pilot of one run per arm is about $1–2. Three runs per arm is about $3–6. A pricier model scales these proportionally.

### How to read the results

- Compare medians, not single runs. Agent runs vary.
- Judge on turns and cost first. Output tokens are secondary.
- Count failed runs (no PDF) separately; a cheap run that produced nothing isn't a saving.
- Open one transcript per arm. Confirm the Rupa arms used Rupa and the render-only arm didn't verify. If an arm misbehaved, fix that before trusting any number.
- Run all arms on the same model on the same day, and pin the model with `MODEL=...`.

## Well-Architected lens

The AWS Well-Architected pillars apply even to a local tool.

| Pillar | How Rupa addresses it |
|---|---|
| Operational excellence | One status line and stable exit codes make it scriptable; CI runs tests and a smoke render on every push |
| Security | Raw HTML escaped; PDF render limited to `file:` and `data:` URLs; Jinja autoescaping; no secrets anywhere |
| Reliability | Input validated before render; every failure maps to an exit code and one message; every PDF checked by `rupa verify` |
| Performance efficiency | No network, no browser process; this 30-plus-page document renders to PDF in a few seconds |
| Cost optimization and sustainability | Fewer turns and output tokens per document, measured rather than claimed; vision spent on sampled pages, not every page |

# Part 3: Tutorial

## Before you start

You need:

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).
- WeasyPrint's system libraries (Pango). On Ubuntu or Debian: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`. On macOS: `brew install pango`. On Windows, use WSL.
- Claude Code, for steps 7 to 9.

The finished project looks like this:

```text
rupa/
├── pyproject.toml
├── README.md
├── src/rupa/
│   ├── __init__.py
│   ├── document.py
│   ├── render.py
│   ├── cli.py
│   ├── verify.py
│   ├── themes/
│   │   ├── default.css
│   │   └── print.css
│   └── references/
│       ├── sample.md     # source for every theme's reference pages
│       └── default/      # cover.png, prose.png, table.png, code.png
├── tests/
│   ├── test_document.py
│   ├── test_cli.py
│   └── test_verify.py
├── plugin/               # Claude Code plugin
├── wants.example.yaml
├── bench/
│   ├── bench.sh
│   ├── summarize.py
│   └── fake/claude     # stand-in for testing the plumbing
└── .github/workflows/ci.yml
```

## Step 1: Scaffold the project

```bash
mkdir rupa && cd rupa
git init
mkdir -p src/rupa/themes tests plugin bench .github/workflows
```

Create `pyproject.toml`. The `[project.scripts]` entry is what makes `rupa` a command once installed. The `pythonpath` setting lets pytest import the package without installing it.

@@include pyproject.toml toml@@

Create `src/rupa/__init__.py`:

@@include src/rupa/__init__.py python@@

Then install everything into a local environment:

```bash
uv sync
```

**Checkpoint:** `uv run pytest` runs and reports that no tests were collected.

## Step 2: The document model

This module turns text into a `Document`: metadata, body HTML and a list of headings. It knows nothing about styling. Note three choices that matter later:

- `html: False` escapes raw HTML in the input.
- Unknown frontmatter keys are an error, not silently ignored.
- Headings are collected from the token stream, which is what the table of contents uses.

`src/rupa/document.py`:

@@include src/rupa/document.py python@@

Write the tests before moving on. `tests/test_document.py`:

@@include tests/test_document.py python@@

**Checkpoint:** `uv run pytest tests/test_document.py -q` shows 8 passed.

## Step 3: The renderer and themes

All styling decisions live in `render.py` and the CSS files. The HTML template is inline so the package has one less file to ship. The PDF function resolves relative images against the input file's folder and refuses to read files outside it.

One trap worth knowing: WeasyPrint's `FatalURLFetchingError` inherits from `BaseException`, not `Exception`, so a plain `except Exception` does not catch it. That is why the code names it explicitly. This was found by a failing test during the build.

`src/rupa/render.py`:

@@include src/rupa/render.py python@@

The screen theme, `src/rupa/themes/default.css`:

@@include src/rupa/themes/default.css css@@

The PDF overrides, `src/rupa/themes/print.css`. This is where text is forced to #000000:

@@include src/rupa/themes/print.css css@@

**Checkpoint:** in `uv run python`, run `from rupa.document import parse; from rupa.render import to_pdf; data, n = to_pdf(parse("## Hi")); print(n)`. It prints a page count.

## Step 4: The CLI contract

The CLI is where the contract from Part 2 becomes code. Notice that the success path prints exactly one line, and that every failure path has its own exit code.

This listing already includes the `verify` and `refs` subcommands from Step 8. They import `verify.py` only when called, so the CLI works before that file exists.

`src/rupa/cli.py`:

@@include src/rupa/cli.py python@@

The CLI tests check the contract, not the implementation: one stdout line, real PDF bytes, the black-text rule, each exit code, and blocked remote resources. `tests/test_cli.py`:

@@include tests/test_cli.py python@@

**Checkpoint:** `uv run pytest -q` shows 16 passed.

## Step 5: Install it as a command

```bash
uv tool install .
echo "# Hello" | rupa -o hello.pdf
```

Expected output:

```text
rupa: wrote hello.pdf (pdf, 1 page, …)
```

Try the failure paths too, since Claude will hit them:

```bash
echo "" | rupa -o x.html          # exit 3: empty input
echo "# x" | rupa -o x.docx       # exit 2: cannot infer format
echo "# x" | rupa -o x.html --theme nope   # exit 4: unknown theme
```

After changing the code, reinstall with `uv tool install --reinstall .`.

## Step 6: Continuous integration

CI installs the PDF system libraries, runs the tests, and does a smoke render. `.github/workflows/ci.yml`:

@@include .github/workflows/ci.yml yaml@@

**Checkpoint:** push to GitHub and confirm the workflow is green.

## Step 7: The Claude Code plugin

Create the three plugin files.

`plugin/.claude-plugin/plugin.json`:

@@include plugin/.claude-plugin/plugin.json json@@

`plugin/skills/render/SKILL.md`. The `description` line is the only part loaded every session, so it carries the whole instruction in one sentence:

@@include plugin/skills/render/SKILL.md markdown@@

`plugin/hooks/hooks.json`. It prints a warning at session start only if the CLI is missing:

@@include plugin/hooks/hooks.json json@@

Validate and load it:

```bash
claude plugin validate ./plugin
# √ Validation passed

claude --plugin-dir ./plugin
```

Plugin names can't start with `claude-` or `anthropic-`; `rupa` is fine.

**Checkpoint:** inside that session, ask Claude whether a skill named `rupa:render` is available. It should say yes. Then ask for a one-page PDF on any topic and check that it wrote Markdown and called `rupa`, rather than writing HTML.

## Step 8: Verification

`src/rupa/verify.py` holds both tiers. It builds a small page model from the PDF (lines with size, weight and position; fill; table area; share of monospace text), runs the checks on that model, and writes the sheets. Keeping the checks on a plain model rather than on pdfplumber objects is what makes them unit-testable.

Two traps found while building it:

- WeasyPrint paints the page background as one large white rectangle. Left in, it makes every page look 100% full and turns every page into a "table". The code filters it out before measuring.
- The cover page ends in a forced page break after the contents, so it is often short by design. It is exempt from the fill checks, as is the last page.
- A reference page that spills onto a second page is a broken reference: the review compares against half a page. The visual review of this document caught exactly that after a sample edit, so `rupa refs` now refuses a sample whose page for any type runs over.

@@include src/rupa/verify.py python@@

The sample document every theme's reference pages come from, `src/rupa/references/sample.md`. Each section is sized to fill one page of its type:

@@include src/rupa/references/sample.md markdown@@

Build the reference pages, and rebuild them whenever the theme changes:

```bash
uv run rupa refs
# rupa: wrote references for 'default' to .../references/default (code=p5, cover=p1, prose=p3, table=p4)
```

The wants file with every default spelled out, `wants.example.yaml`. A test keeps it in sync with the code:

@@include wants.example.yaml yaml@@

The tests, `tests/test_verify.py`. Most build synthetic pages, so each check is tested in isolation, and two run against a real render:

@@include tests/test_verify.py python@@

**Checkpoint:** `uv run pytest -q` shows 40 passed, and `rupa verify hello.pdf` prints a line starting with `verify:` and writes a `hello.verify/` folder with sheets and `verify.json`.

**Checkpoint in Claude Code:** with the plugin loaded, ask for a one-page PDF and to verify it. Claude should render, run `rupa verify`, open the sheet, give a verdict per sheet, and fix the Markdown if something fails.

## Step 9: Measure

`bench/bench.sh` sets up the three arms and runs them. The `awk` line builds the render-only plugin by dropping everything from `## Verify` up to the skill's closing line:

@@include bench/bench.sh bash@@

`bench/summarize.py` reads one results folder and prints the tables:

@@include bench/summarize.py python@@

Before spending anything, test the plumbing with a stand-in for `claude` that writes a fake `report.pdf` and prints canned JSON. During the build this showed each arm getting the right plugin and the summary computing the comparisons correctly. `bench/fake/claude`:

@@include bench/fake/claude bash@@

```bash
PATH="$PWD/bench/fake:$PATH" bench/bench.sh 2
# ...
# rupa         turns -40%   cost -40%
# rupa-verify  turns -25%   cost -25%
```

Those numbers come from the stand-in, not from Claude.

Then run the pilot, one run per arm, and check the transcripts:

```bash
chmod +x bench/bench.sh
bench/bench.sh
```

If all three arms behaved, run three per arm on a pinned model:

```bash
MODEL=claude-sonnet-5-5 bench/bench.sh 3
```

Record the medians in your README with the date, model and task. If a Rupa arm isn't cheaper, read its transcript before changing anything else.

## Step 10: What to build next

In rough order of value:

1. **Run the pilot, then the benchmark,** and write the result down. Everything else depends on whether Rupa really cuts turns and cost.
2. **A second theme**, such as your dark slate and cyan look for screen HTML, with its own reference pages and a test that renders and verifies every theme.
3. **A golden-render test in CI** that verifies the sample document against its own references, so a CSS change that breaks the look fails the build.
4. **Callouts** (note, warning) through a small markdown-it plugin, so Claude never needs raw HTML for them.
5. **A `--watch` mode** for live preview while you edit by hand.
6. **More targets** (DOCX through python-docx) behind the same contract and exit codes.
7. **Harness integration.** Rupa is a plain CLI, so the Pramā harness can call it the same way Claude Code does.

# Turning the build into a showcase

If this becomes a second project about how you built Rupa, capture material as you go rather than reconstructing it afterward.

- **One commit per milestone,** with the milestone number in the message. The git log becomes the outline.
- **A decision log.** The Key decisions table in Part 1 is the start; add a row whenever you change your mind, with the reason.
- **The numbers.** The three-arm tables, with model, date and task. Lead with turns: that's the finding.
- **Before and after artifacts.** The same report produced by hand-written HTML and by Rupa, side by side.
- **The failures.** The WeasyPrint `BaseException` trap, the API change, the background rectangle, and the code wrap that only the visual review caught are exactly the kind of detail that makes a build write-up credible.
- **The verification records.** Each `verify.json` and its sheets show what was checked and what was found. The appendix of this document is one.

A natural shape for a write-up or Loom entry: the problem (each turn re-reads everything, and markup work adds turns), the split (content versus form), the contract, the verification loop, the measurement, and what the numbers showed. The showcase can itself be rendered by Rupa.

@@verification-record@@
