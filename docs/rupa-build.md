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

Everything in Part 3 was built and run before this was written: every test passes, `claude plugin validate` passes, and Claude Code loads the skill and uses it to render and verify a PDF on its own. This document was rendered by that prototype from one Markdown file, then checked with `rupa verify` and a visual review of its sample pages. The appendix records what that review found.

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
| M1 | Parser | Document model and its parser tests pass | 2–3 hours |
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
| `-o PATH` | The rendered file. Format comes from the extension, or `--to html` / `--to pdf`. With `--to`, an existing file that isn't `.html` or `.pdf` is replaced only with `--force` |
| stdout | One status line, or one JSON object with `--json`. Never the document |
| stderr | One error line on failure |
| exit code | `0` ok, `2` usage, `3` bad input, `4` render failure, `5` verify checks failed or a PDF still over its page budget |

Two subcommands follow the same rules:

| Command | Does | Prints |
|---|---|---|
| `rupa verify OUT.pdf [--wants F]` | Runs the checks, writes sheets and `verify.json` | One line: checks passed, failures, sheet count |
| `rupa refs [--theme T]` | Rebuilds a theme's reference pages from the bundled sample | One line: which sample page became each reference |

A Markdown file named `verify` or `refs` is read as the subcommand; write `./verify` to render it.

Example:

```bash
$ rupa notes.md -o out/notes.pdf
rupa: wrote out/notes.pdf (pdf, 3 pages, 48,211 bytes)

$ rupa notes.md -o out/notes.pdf --json
{"ok": true, "path": "out/notes.pdf", "format": "pdf", "pages": 3, "bytes": 48211}
```

### Fonts

PDFs embed Inter and JetBrains Mono from `src/rupa/themes/fonts/` (both SIL Open Font License 1.1, licences alongside). Before that, a PDF used whatever the machine had: on a machine without Inter the theme fell back to Liberation Sans, the reference pages no longer matched the renders, and the fit numbers drifted. The image guard lets the renderer read that one folder besides the document's own.

### Page budgets

`pages: N` in the frontmatter (or `--pages N`) gives a PDF a page budget. If the first render is over, Rupa tightens the form, never the content, one step at a time: it drops the contents list, then sets compact type, then tight type. Margins and heading sizes stay fixed, because `verify` measures against them. The status line names the steps used:

```bash
rupa: wrote out/report.pdf (pdf, 2 pages, fit to 2 with no contents + compact type, 41,322 bytes)
```

If even tight type is over, Rupa still writes the file. It exits `5` and says how many words sit past the budget, so Claude cuts that much in one edit instead of measuring pages itself:

```bash
rupa: wrote out/report.pdf (pdf, 3 pages, 44,870 bytes); over the 2-page budget at the tightest type: cut about 140 words and render again
```

## Input format

Frontmatter is optional. Only these keys are accepted; anything else is exit code 3, so typos fail loudly instead of being ignored. A value of the wrong type (`title: [a, b]`, `toc: "false"`) is exit 3 too, and so are YAML aliases (`*name`), since a short chain of them can expand a few lines into megabytes. A number or date in a text field is fine: `title: 1984` is the text 1984.

| Key | Type | Effect |
|---|---|---|
| `title` | string | Cover title and PDF running footer. Defaults to the first heading |
| `subtitle` | string | Line under the title |
| `author` | string | Byline |
| `date` | string | Byline, after the author |
| `theme` | string | Theme name. Defaults to `default`; `--theme` overrides it |
| `toc` | bool | Table of contents from `#` and `##` headings. Defaults to true |
| `pages` | whole number | PDF page budget (see above) |

Body conventions:

- `#` is a part. In PDF each part starts a new page, so the skill keeps parts for long documents (about 8 pages or more); in a short one they leave half-empty pages.
- `##` is a section, `###` a subsection. Sections get anchors automatically.
- Fenced code blocks take a language tag for highlighting.
- Tables use GitHub pipe syntax. `~~strikethrough~~`, task lists (`- [ ]`, `- [x]`) and footnotes (`[^1]`) work too; in a PDF the footnotes are collected at the end.
- Raw HTML is escaped and shown as text.
- Images must be relative paths next to the Markdown file, or `data:image` URIs. A URL, an absolute path or a `data:image` URI of any other type is bad input (exit code 3); a missing file, a hidden one, one outside the Markdown file's folder, or one that doesn't decode as a PNG, JPEG, GIF, WebP or SVG image fails the render (exit code 4). HTML output embeds each image as a data URI, so the file can be sent on its own.

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

To add a theme, copy `default.css` to `newname.css`, change the variables at the top, add the name to `THEMES` and its PDF text colours to `THEME_TEXT_COLORS` in `render.py`, and run `rupa refs --theme newname` to build its reference pages. The golden-render test then covers it with no new test code.

A theme can also carry a print layer, `newname.print.css`, appended after `print.css` for PDF only. Two themes use one: `cyan` and `cyan-dark`, built from the Cyan Signature system used for slide decks (deep navy, one cyan accent, Hanken Grotesk with JetBrains Mono labels, green-dot pill badges, rounded panels). They share `cyan.css` for screen through `THEME_BASE`. The `cyan` print layer turns the page white and every glyph black, keeping the type and cyan rules; `cyan-dark` keeps the navy page and prints in the deck's own ink, cyan and greys, which verify accepts because they're listed for it. Each render records its theme in the PDF's keywords, so `rupa verify` picks the right reference pages and colours without being told.

WeasyPrint shaped the print layers. It paints a page background from the text area down, so a glow at the top edge got a hard line; the dark PDF keeps the gradient and drops the glow. It has no `fit-content` and centres flex items by shrinking them, so pills are `display: table` and the PDF cover is a centred block. The sample's code page was 97% full in the default theme, so the pill above each part title pushed it onto a fifth page; the sample now has seven functions, not eight, to leave every theme room.

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
| `figure-gap` | A page is under 70% full and a figure opens the next page (not before a part, not if already near-empty or sparse) |
| `heading-at-bottom` | A heading is the last line on a page, or a heading and one line end it and the next page doesn't open with a heading |
| `overflow` | Text runs past the side margins |

**Tier 2: visual review.** Code can't tell whether a page looks right. For that, `rupa verify` classifies each page as cover, prose, table or code. It then writes a sheet image for every page a code check flagged (with `sample: per-type`, one page of each type too), with the theme's reference page on the left and the rendered page on the right. Claude opens those sheets and judges each one against a fixed rubric: hierarchy, spacing, overflow, page balance and style.

### The wants file

A `wants.yaml` holds what a finished PDF must satisfy. Every key is optional, unknown keys are an error, and `wants.example.yaml` in the repo spells out the defaults. A project that needs A4 and a 10-page limit writes two lines:

```yaml
page_size: a4
max_pages: 10
```

### Reference pages

A theme's reference pages are its picture of itself. `rupa refs` renders a bundled sample document with the theme and saves the most typical page of each type as a PNG inside the package (`src/rupa/references/<theme>/`). That default only works in a source checkout; an installed `rupa refs` needs `--out`, so it can't overwrite the pages verify compares against. Rebuild them whenever the theme's CSS changes, and commit them with it. A golden-render test (`tests/test_golden.py`) holds you to that: for every theme it renders the sample, requires it to pass verify, rebuilds the reference pages in a temporary folder, and fails if any of them differs from the committed PNG in more than 0.5% of its pixels. The tolerance covers antialiasing differences between Pango builds; a moved margin fails it. A sheet without a reference still shows the page, labeled so.

### What it costs

An image costs roughly its width times height divided by 750 in input tokens. A sheet at the default 90 DPI is about 1,530 × 1,020 pixels, or about 2,000 tokens.

| How Claude reviews the 31-page version of this document | Images | Input tokens, approx. |
|---|---|---|
| Every page at full resolution | 31 | 85,000 |
| `rupa verify`: flagged pages plus one per type | 5 | 10,000 |
| Code checks only | 0 | under 100 |

The sampled review scales with how varied the document is, not how long it is. That is the right place to spend tokens: the reader sees the result.

### The loop

The skill tells Claude to render, verify, open the sheets, and write one verdict per sheet. Claude fixes failures in the Markdown only: split a table that runs past the margin into two that repeat the first column, shorten a code line, move content around an awkward break. The `overflow` detail in `verify.json` says what ran over and by how much (`p1 table by 13pt`), so Claude knows which fix applies. Then it renders and verifies again, at most twice. A problem that can only be fixed in CSS is reported as a theme issue rather than patched, so one document's quirks don't leak into the theme.

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

### Arms

`bench/bench.sh` runs the same task in four arms through Claude Code's print mode (`claude -p ... --output-format json`):

| Arm | Setup | Answers |
|---|---|---|
| `baseline` | No plugin | What it costs today |
| `rupa` | Plugin with the skill's Verify section removed | What rendering through Rupa saves |
| `rupa-pertype` | Plugin whose skill runs `rupa verify --sample per-type` | What verify costs when every page type gets a sheet, even on a clean PDF |
| `rupa-verify` | Plugin as shipped (sheets only for flagged pages) | What the visual review adds back |

The first benchmark called the flagged arm `rupa-flagged`, when per-type was still the default; `summarize.py` still reads that name. The render-only and per-type arms use copies of the plugin made at run time, so all four arms get exactly the same prompt. Each run starts in a fresh empty directory, so no arm can read the Rupa repo. `bench/summarize.py` prints one row per run and the medians per arm, with turns and cache reads first, then a line comparing each Rupa arm to the baseline.

### First result (2026-10-15)

Three runs per arm, Claude Opus 5.5, task: "Write a 2-page PDF report on the AWS Well-Architected security pillar, saved as report.pdf." Every run produced a PDF. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 9 | 299,095 | $0.43 | — |
| `rupa` | 10 | 296,826 | $0.40 | turns +11%, cost −7% |
| `rupa-flagged` | 13 | 438,591 | $0.43 | turns +44%, cost 0% |
| `rupa-verify` (per-type sheets) | 15 | 523,338 | $0.55 | turns +67%, cost +27% |

Rupa didn't save turns. The transcripts show why, and it isn't rendering:

- **Every Rupa run went over two pages on its first render** (three or four pages). The default contents list takes a page break, and Claude wrote a first draft longer than two pages. Baseline overshot too, but fixed it in one turn by editing its own CSS (`font-size`, margins). Rupa's form is fixed, so Claude cut content instead, probing each round with `pdftotext | wc -w`. One run took seven cut-and-render rounds.
- **The flagged arm threw its saving away.** On a clean PDF verify made no sheets, so Claude rendered the pages with `pdftoppm` and looked anyway.
- Baseline never detoured to find or install a PDF tool on this machine: Chrome and reportlab were already there. The estimate above assumed it would.

What changed in response: page budgets (above), so Rupa does the density fitting baseline did by hand and gives a word count when cutting is unavoidable; the skill sets `pages` when the user asks for a length, writes about 450 words per page, and doesn't look at pages when verify made no sheets; `sample: flagged` is now the default. A run of three per arm costs about $6 on Opus.

### Second result (2026-10-16)

Same task, model and runs, after page budgets and flagged-only sampling. Every run produced a 2-page PDF. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 10 | 351,496 | $0.46 | — |
| `rupa` | 5 | 152,505 | $0.27 | turns −50%, cost −42% |
| `rupa-pertype` | 9 | 247,766 | $0.36 | turns −10%, cost −22% |
| `rupa-verify` (as shipped) | 6 | 153,765 | $0.28 | turns −40%, cost −39% |

Every Rupa run set `pages: 2` and fitted on its first render, so none cut content or measured pages. The shipped arm is one render plus one `verify` that came back clean, with no sheets to open. Per-type sampling costs about three extra turns for sheets on a PDF that has nothing wrong with it, which confirms flagged as the default. The Rupa runs were also tighter: the slowest shipped run took 6 turns, against 20 before.

One caveat: the Rupa reports are shorter. Median text was about 850 words against about 1,180 for baseline, because baseline packs the page with smaller margins and type, and Rupa keeps the theme's margins. Some of the saving is less writing (median output 3,100 tokens against 7,150). For a fixed page count that's a fair trade, but it is a difference in the product as well as in cost.

### Harder task (2026-10-16)

`TASK=guide`: a 3-page IAM Identity Center guide with a five-column table, a CLI example, a JSON policy of at least 25 lines and a numbered checklist. Three runs per arm, Opus 5.5. Every run produced a 3-page PDF with all four required parts. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 20 | 786,720 | $0.85 | — |
| `rupa` | 14 | 348,457 | $0.47 | turns −30%, cost −46% |
| `rupa-pertype` | 17 | 312,611 | $0.53 | turns −15%, cost −38% |
| `rupa-verify` (as shipped) | 7 | 249,016 | $0.35 | turns −65%, cost −59% |

The gap widens with layout work. Baseline built the PDF with reportlab or Chrome, then went round after round adjusting page breaks and spacing and checking page images, writing 17,700 output tokens per run. The Rupa arms wrote less than half that.

The Rupa runs still spent turns cutting. The first draft was always over 3 pages at the tightest type, and the "cut about N words" estimate ran low: most runs took two to four cut rounds. Rupa counted the words on the overflow pages, but here the overflow was mostly the JSON policy, which has one or two words a line, so "cut 34 words" meant about fifteen lines of space. The estimate now measures the height used past the budget and converts it to prose words at tight type, plus 10%. On a guide-like sample it asked for 177 words, and one cut of that size fitted. The three-arm medians above predate this fix. The render-only arm happens to be slower than the shipped arm here (14 turns against 7); with three runs that's noise from how many cut rounds each run needed.

Rupa's guides again carry fewer words (about 750 against 1,300), for the same reason as before.

### Harder task, with bundled fonts (2026-10-16)

Same guide task after the switch to bundled Inter and JetBrains Mono and the height-based estimate. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 18 | 854,510 | $0.94 | — |
| `rupa` | 7 | 204,375 | $0.39 | turns −61%, cost −58% |
| `rupa-pertype` | 15 | 311,164 | $0.53 | turns −17%, cost −44% |
| `rupa-verify` (as shipped) | 12 | 206,585 | $0.42 | turns −33%, cost −56% |

Cost held, but cutting was still the weak spot. Every Rupa run went over 3 pages on its first render, and only 3 of the 6 render-only and shipped runs fitted after one cut. The runs that were told to cut a lot cut too much: they fitted at compact type with half a page spare, at 518 to 578 words. The cause was the unit. The hint was in words, but a code line or a table row frees several times the space of a prose word, so a run that cut code to meet a word count overshot. Claude also spent one turn per Edit.

What changed in response: the over-budget hint now asks for lines ("cut about 4 lines (a line of prose is about 18 words; a code line or table row is one line)"), and the skill plans about 30 lines per page before writing and makes all cuts in one turn.

### Harder task, cuts in lines (2026-10-16)

Same task after the lines-based hint and the per-page line plan. Every run produced a 3-page PDF. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 23 | 1,051,781 | $1.19 | — |
| `rupa` | 5 | 107,903 | $0.28 | turns −78%, cost −76% |
| `rupa-pertype` | 15 | 359,063 | $0.49 | turns −35%, cost −59% |
| `rupa-verify` (as shipped) | 6 | 155,203 | $0.31 | turns −74%, cost −74% |

The line plan mostly removed cutting. 7 of the 9 Rupa runs fitted on their first render, all three render-only runs took exactly 5 turns, and two of the three shipped runs were one render plus a clean verify. Baseline was costlier than in either earlier guide run ($1.19 against $0.85 and $0.94). Agent runs vary, so the percentages are wider than the true gap; the shipped arm's own cost ($0.31) is the steadier number.

Two runs still cut. One shipped run was asked to cut 4 lines, cut too little, was asked for 4 more and fitted: two rounds, with seven Edits in separate turns, so "all cuts in one turn" doesn't always hold. The skill now says how: rewrite the whole Markdown file with one Write, not a series of Edits, for budget cuts and verify fixes alike. The tight task below tests it. One per-type run fitted, then pushed itself back over the budget while fixing what it saw on the per-type sheets.

The plan errs short. Most runs fitted only once Rupa dropped to compact type, so they weren't over-cut, but the Rupa guides still carry about 740 words against baseline's 1,260. Baseline gets its extra words by shrinking margins and type: every baseline PDF fails `rupa verify`'s `overflow` and `text-color` checks.

One layout fault turned up in run 4's PDFs: a heading and a one-line lead-in ("Run from the delegated administrator account:") at the bottom of page 1, with the code block moved whole to page 2. Print CSS now keeps a paragraph with the code block or table that follows it and a heading's first list item with the second, and `heading-at-bottom` also flags a heading with one line directly under it at a page end.

### Report task, current build (2026-10-16)

The 2-page report task again, with the bundled fonts, the line plan and the break rules above. Every run produced a 2-page PDF. Medians:

| Arm | Turns | Cache reads | Cost | vs baseline |
|---|---|---|---|---|
| `baseline` | 13 | 505,643 | $0.52 | — |
| `rupa` | 5 | 152,505 | $0.26 | turns −62%, cost −50% |
| `rupa-pertype` | 9 | 246,035 | $0.34 | turns −31%, cost −36% |
| `rupa-verify` (as shipped) | 7 | 199,354 | $0.29 | turns −46%, cost −45% |

All nine Rupa runs fitted on their first render, so none cut anything, and every Rupa PDF passes `rupa verify` while every baseline PDF fails `text-color`. The shipped arm cost about the same as in the second result ($0.29 against $0.28); two of its runs spent one extra turn listing the folder to confirm `report.pdf` was there. Rupa's reports came in at about 720 words against baseline's 1,180, down from about 850 in the second result: the line plan makes Claude write to the theme's density rather than past it.

### Tight task: cuts in one Write (2026-10-16)

`TASK=tight`, the guide in two pages, so the run has to cut. Rupa arms only (`ARMS="rupa rupa-verify"`), three runs each, Opus 5.5, after the skill started telling Claude to cut by rewriting the whole file with one Write. Medians:

| Arm | Turns | Cache reads | Cost |
|---|---|---|---|
| `rupa` | 7 | 102,557 | $0.33 |
| `rupa-verify` (as shipped) | 8 | 139,791 | $0.36 |

Five of the six runs went over the budget on the first render, asking for cuts of 7 to 31 lines. All five cut with a single Write of the whole file and fitted on the next render: one cut round each, with no Edits in any run. The sixth fitted at first. Every PDF passes `rupa verify` and keeps all four required parts, with policies of about 29 to 35 lines. A run that has to cut costs two turns (a Write and a render) on top of a run that fits at once, which is all a cut should cost.

### Wide task: shortening instead of splitting (2026-10-16)

`TASK=wide`, an EC2 sizing guide whose table must keep all eleven columns. One `rupa-verify` run, Opus 5.5: 16 turns, $0.70. The table overflowed; Claude shortened cell text for two fix rounds, still ran 13pt over, and reported a theme issue. It never split the table, though the skill listed that fix, and verify said only "text extends past the side margins". Now the `overflow` detail names what runs over and by how much (`p1 table by 13pt`), and the skill says to split an overflowing table into two that repeat the first column. One run: a failure mode, not a cost. After the change, a single run split the table on its first fix round and passed: 8 turns, $0.37.

### Wide task, all arms (2026-10-16)

`TASK=wide`, three runs per arm, Opus 5.5, after the overflow and split changes. Medians:

| Arm | Turns | Cost | PDFs passing verify |
|---|---|---|---|
| baseline | 11 | $0.54 | 0 of 3 (own margins and colors) |
| `rupa` (render only) | 5 | $0.31 | 0 of 3: table overflows |
| `rupa-pertype` | 17 | $0.64 | 2 of 3 |
| `rupa-verify` (as shipped) | 12 | $0.47 | 3 of 3 |

Every Rupa first draft overflowed, by 31 to 85pt. Of the six runs that verified, two split the table on the first fix round and two shortened cells first and split on the second. Two only shortened: one fitted, and a per-type run stayed 25pt over and shipped with the failure reported. The runs that shortened first read "a table … across eleven columns" as forbidding a split. Every fix round was a Python rewrite of the Markdown rather than the one Write the skill asks for, which cost nothing extra here.

This is the one task where baseline did well. It never clipped the table: two runs put it on a landscape page and one fitted it on portrait with half-inch margins, at 7.4pt and 6.6pt type (one header broke mid-word). Rupa can't change orientation or shrink one table, so it restructures instead and keeps 9.8pt type. That costs fix rounds: the shipped arm saved only 13% on cost and took one more turn. The render-only arm is cheapest but shipped every table overflowing, so on this task verify is what makes the output correct. A theme option for wide tables would cut the fix rounds; the next build adds one.


### Wide tables in smaller type (2026-10-16)

`print.css` now sets a table of 9 or more columns in 8pt type, 11 or more in 7.5pt, with tighter cell padding; the old padding alone took about 160pt of an 11-column table's 497pt. The skill tells Claude that about 11 short columns fit and to write two tables beyond that. Re-rendered with the new rule, all nine Rupa first drafts from the full wide run fit, where all nine had overflowed. One draft still fails verify on a separate problem: a 180-character `--query` in a code block, which Rupa wraps only at spaces so a command is never silently broken.

Measured with `TASK=wide ARMS="rupa rupa-verify"`, three runs each, Opus 5.5. Baseline is the full run above; it doesn't use Rupa, so the change can't affect it.

| Arm | Turns | Cost | PDFs passing verify |
|---|---|---|---|
| baseline (full run above) | 11 | $0.54 | 0 of 3 |
| `rupa` (render only) | 5 | $0.32 | 3 of 3 |
| `rupa-verify` (as shipped) | 6 | $0.33 | 3 of 3 |

Every run fitted on its first render, with no fix rounds: one Write, one render, and for the shipped arm one clean verify. Each kept a single eleven-column table at 7.5pt, carried across a page break with its header repeated. Against baseline the shipped arm takes 45% fewer turns and costs 40% less, in line with the other tasks, where before the rule it saved 13%. Render-only now ships correct tables too, so on this task verify is a check that passes rather than the step that makes the output right.

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

**Checkpoint:** `uv run pytest tests/test_document.py -q` passes every test in the file.

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

**Checkpoint:** `uv run pytest -q` passes every test.

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

Create the three plugin files, starting with `plugin/.claude-plugin/plugin.json`:

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
# rupa: wrote references for 'default' to .../references/default (code=p4, cover=p1, prose=p2, table=p3)
```

The wants file with every default spelled out, `wants.example.yaml`. A test keeps it in sync with the code:

@@include wants.example.yaml yaml@@

The tests, `tests/test_verify.py`. Most build synthetic pages, so each check is tested in isolation, and two run against a real render:

@@include tests/test_verify.py python@@

**Checkpoint:** `uv run pytest -q` passes every test, and `rupa verify hello.pdf` prints a line starting with `verify:` and writes a `hello.verify/` folder with `verify.json` (plus a sheet for any flagged page).

**Checkpoint in Claude Code:** with the plugin loaded, ask for a one-page PDF and to verify it. Claude should render, run `rupa verify`, open the sheet, give a verdict per sheet, and fix the Markdown if something fails.

## Step 9: Measure

`bench/bench.sh` sets up the four arms and runs them. The `awk` line builds the render-only plugin by dropping everything from `## Verify` up to the skill's closing line, and the `sed` line builds the per-type plugin by adding `--sample per-type` to the verify command:

@@include bench/bench.sh bash@@

`bench/summarize.py` reads one results folder and prints the tables:

@@include bench/summarize.py python@@

Before spending anything, test the plumbing with a stand-in for `claude` that writes a fake `report.pdf` and prints canned JSON. During the build this showed each arm getting the right plugin and the summary computing the comparisons correctly. `bench/fake/claude`:

@@include bench/fake/claude bash@@

```bash
PATH="$PWD/bench/fake:$PATH" bench/bench.sh 2
# ...
# rupa          turns -40%   cost -40%
# rupa-pertype  turns -15%   cost -15%
# rupa-verify   turns -25%   cost -25%
```

Those numbers come from the stand-in, not from Claude.

Then run the pilot, one run per arm, and check the transcripts:

```bash
chmod +x bench/bench.sh
bench/bench.sh
```

Prompts live in `bench/tasks/`, one file per task, and `TASK=<name>` picks one (default `report`, the two-page prose report). `guide` is a harder three-page task with a five-column table, a CLI example and a 25-line JSON policy, closer to where hand-written HTML has to work for its layout. `tight` is the guide squeezed into two pages: the required parts alone fit only at tight type, so any real prose goes over the budget and the run has to cut. It exists to test how Rupa runs cut, so run it on the Rupa arms only: `ARMS="rupa rupa-verify"` picks which arms run (default all four). `wide` is a three-page EC2 sizing guide whose table has eleven columns, every one required; at the default type eight columns fit and ten already run off the page, so a run has to split the table rather than drop columns. The render-only `rupa` arm never runs verify, so it is the one most likely to ship a clipped table. Each results folder is named after its task and keeps a copy of the prompt in `task.txt`.

If all four arms behaved, run three per arm on a pinned model:

```bash
MODEL=claude-sonnet-5-5 bench/bench.sh 3
```

Record the medians in your README with the date, model and task. If a Rupa arm isn't cheaper, read its transcript before changing anything else.

## Step 10: What to build next

In rough order of value:

1. **Re-run `TASK=guide`** to confirm the height-based cut estimate brings the cut rounds down to one. Then a harder benchmark task (tables, code, a wide table that must be split), where hand-written HTML should struggle more than it did on a two-page prose report.
2. **A second theme**, such as your dark slate and cyan look for screen HTML, with its own reference pages; the golden-render test picks it up from `THEMES` with no new test code.
3. **Callouts** (note, warning) through a small markdown-it plugin, so Claude never needs raw HTML for them.
4. **A `--watch` mode** for live preview while you edit by hand.
5. **More targets** (DOCX through python-docx) behind the same contract and exit codes.
6. **Harness integration.** Rupa is a plain CLI, so the Pramā harness can call it the same way Claude Code does.

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
