---
title: Rupa Bench v2
subtitle: Held-out tasks, a hinted baseline, two models, judged quality
author: Vajra Sarpa
date: 19 October 2026
---

## Summary

Rupa `v0.1.2` was run against Claude Code alone on six tasks it was never
tuned on, four it was tuned on, and a five-document session: 210 runs on
Claude Opus 5.5 and Sonnet 5.5, 18–19 October 2026. The hypotheses and pass
rules were registered before any paid run (`bench/PREREG.md`, commit
`237afc2`).

- **Cost: confirmed.** On the held-out tasks Rupa was cheaper on every task
  against both baselines. On Opus it cost 0.56× Claude Code alone (90%
  interval 0.51–0.60) and 0.63× Claude Code with a three-line hint
  (0.56–0.65). It was also about 1.7× faster and added about half the context.
  Sonnet showed the same direction, with a smaller margin.
- **Quality: not shown.** Every run made its document, and a per-item
  checklist found Rupa's documents about as complete (0.97 against 0.99). But
  head to head, an LLM judge preferred the baseline's document in 47 of the 70
  held-out Opus pairs and Rupa's in 5, with 18 ties. Its stated reasons:
  Rupa's documents are thinner, and its page breaks leave gaps and orphaned
  rows. The pre-registered quality rule (H2) fails against both baselines on
  both models.
- **Reliability: equal.** No run in any arm failed.
- **The v1 claims mostly hold for cost.** The held-out saving (44%) is
  smaller than v1's 40–74% on tuned tasks, and smaller than v2's own result
  on the seen tasks (52%). The v1 line "0 of 9 baseline PDFs pass verify"
  measured Rupa's house style: neutral checks pass almost every baseline PDF.

By the registered rule, which used the LLM judge, "Rupa makes documents
more cheaply without making them worse" does not hold. The human check
changes the reading: on 15 blind pairs Vajra found the content equally good
in 12 of 13 and preferred the baseline's layout in 7 of 15. The supported
claim is: Rupa makes documents about 40% cheaper and 1.7× faster with the
same content, and its layout on longer documents is weaker and needs a theme
fix. One layout fault is a plain bug: every image wider than the text column
runs off the page (all 8 Rupa lab reports), and nothing in Rupa caught it.

## What was run

| Set | Tasks | Arms | Runs per arm | Runs |
|---|---|---|---|---|
| Main, Opus 5.5 | 6 held-out, 4 seen | 3 | 5 | 150 |
| Sonnet 5.5 | 6 held-out | 3 | 3 | 54 |
| Session, Opus 5.5 | 5 documents in one session | 2 | 3 | 6 |

Arms: `baseline` (Claude Code alone), `baseline-hinted` (plus a three-line
`CLAUDE.md`: write HTML with a print stylesheet, print with headless Chrome,
check the page count) and `rupa-verify` (the plugin as tagged). Every run was
`claude -p` in a fresh folder with user plugins, skills and MCP servers off,
arms interleaved in a seeded order, Rupa frozen at `v0.1.2`. Costs are Claude
Code's list-price figures; the runs billed to a Claude plan. The runs came to
$93.79 at list price, and the judge to $19.40 (425 calls).

Held-out tasks: a one-page CV; a five-page lab report from a supplied CSV and
chart; a ten-page handbook; a two-page postmortem from supplied notes; an
HTML explainer; and a two-page report revised in the same session. Seen
tasks: v1's report, guide, tight and wide.

## Cost and time

Opus, held-out tasks, medians of five runs:

| Task | Claude Code | Hinted | Rupa | Rupa time vs Claude Code |
|---|---|---|---|---|
| CV, 1 page | $0.22 | $0.17 | $0.14 | 27 s vs 42 s |
| Lab report, 5 pages | $0.76 | $0.65 | $0.32 | 73 s vs 180 s |
| Handbook, 10 pages | $0.68 | $0.60 | $0.49 | 137 s vs 167 s |
| Postmortem, 2 pages | $0.31 | $0.30 | $0.17 | 31 s vs 66 s |
| HTML page | $0.26 | $0.22 | $0.18 | 41 s vs 59 s |
| Report then revision | $0.92 | $0.98 | $0.42 | 62 s vs 128 s |

| Held-out, geometric mean ratio, Rupa / other | Cost | Time | Context added | Turns | Words |
|---|---|---|---|---|---|
| Opus, vs Claude Code | 0.56 | 0.57 | 0.48 | 0.74 | 0.84 |
| Opus, vs hinted | 0.63 | 0.60 | 0.59 | 0.83 | 0.89 |
| Sonnet, vs Claude Code | 0.67 | 0.69 | 0.66 | 1.04 | 1.01 |
| Sonnet, vs hinted | 0.79 | 0.80 | 0.87 | 1.31 | 1.05 |

On the seen tasks Rupa cost 0.48× Claude Code alone and 0.39× hinted. The
hint made Claude Code cheaper on the short held-out tasks and dearer on the
fit-to-length ones (`tight`, `wide`, `revise`), where it took 1.5 to 2.4
times as many turns.

Five documents in one session (three PDFs of 1–3 pages, an HTML page, a
one-page status note): Rupa $1.88 against $4.52, 153 s against 391 s, and
16,000 tokens of context added against 55,000.

## Quality

Three measures, the same for every arm.

**Mechanical checks** (page count, text inside the page and clear of the
edge, smallest text at least 6 pt, required phrases, JSON parses, numbered
list, image present, HTML self-contained): nearly everything passed in every
arm. The exceptions are artefacts of the method:

- `lab`: every baseline run drew its own extra charts as vector graphics,
  with axis labels at 1.5–4 pt; Rupa embedded the supplied PNG, whose labels
  aren't text, so the size check can't see them.
- `session`: two Rupa PDFs "missed" the phrase *performance efficiency*
  because it sits in a wrapped table cell that text extraction splits.

**Judge, one document at a time** (Claude Sonnet 5.5, page images, the task's
checklist): requirement scores 0.97 for Rupa against 0.99 for both baselines
on Opus, 0.97 against 0.98 on Sonnet. Rupa's layout scores were lower (median
2 on `lab`, 3 on `handbook`, against 4 for the baselines).

**Judge, head to head** (A and B in a seeded random order; Rupa lost about
equally often as A, 44, and as B, 43, so position bias isn't the cause):

| Set | "Does what was asked": Rupa wins / losses / ties | "Laid out and readable" |
|---|---|---|
| Opus, held-out | 5 / 47 / 18 | 14 / 56 / 0 |
| Opus, seen | 0 / 40 / 0 | 21 / 19 / 0 |
| Opus, session | 5 / 10 / 0 | 8 / 7 / 0 |
| Sonnet, held-out | 5 / 28 / 9 | 17 / 23 / 2 |

Of the 87 Opus losses on "does what was asked", the judge called Rupa's
document thinner or less detailed in about half, and named empty space,
page breaks or orphaned rows in about half. On Opus, Rupa documents hold
fewer words at the same page count (0.84× on held-out tasks, about 0.6× on
the seen ones), because the theme keeps its margins and type size. On Sonnet
the word counts are level, and Rupa still loses 5 to 28, so length isn't the
whole story.

**Human check** (Vajra, 15 random Opus held-out pairs, blind; 28 of 30
questions answered):

| Same 15 pairs | "Does what was asked": Rupa wins / losses / ties | "Laid out and readable" |
|---|---|---|
| Vajra | 0 / 1 / 12 (13 answered) | 1 / 7 / 7 |
| LLM judge | 0 / 9 / 6 | 2 / 13 / 0 |

He agreed with the LLM judge on 4 of 13 content answers and 7 of 15 layout
answers. On content he saw no real difference: 12 ties in 13. On layout he
preferred the baseline in 7, including every handbook and two of the three
lab reports, and Rupa in 1. So the judge's "thinner" verdict doesn't hold for
a human reader, and Rupa's layout on longer documents is a real, moderate
weakness. The LLM pairwise judge is harsher than a person and leans toward
denser pages.

His notes after judging: some pages had much more empty space than the
other document's; on a couple of pages part of a graph was missing; and he
liked the bold front page in some documents. The missing graphs were Rupa's
(see the next section).

## Pre-registered rules

Opus, held-out tasks:

| | vs Claude Code | vs hinted |
|---|---|---|
| H1 cost: cheaper on ≥4 of 6, 90% interval below 1 | holds: 6 of 6, 0.51–0.60 | holds: 6 of 6, 0.56–0.65 |
| H2 quality: checklist within 0.05, and not losing over half the decided pairs | fails: 0.97 vs 0.99, but lost 23 of 26 decided | fails: 0.97 vs 0.99, lost 24 of 26 |
| H3 reliability | holds: no failures | holds: no failures |

Sonnet: H1 holds (0.60–0.71; 0.74–0.85), H2 fails (lost 14 of 16 decided
pairs against Claude Code alone, 14 of 17 against hinted), H3 holds.

## What changed from v1

- **Isolation.** A plain `claude -p` on this machine now loads the
  user-installed Rupa plugin, 116 skills and 39 MCP servers; v2 turns them
  off. Without that, the v2 baselines would have had the Rupa skill. All 22
  v1 baseline transcripts were checked: none used Rupa.
- **The cost floor was partly the machine's setup.** v1 reported about
  $0.19 a run just to start; with nothing extra loaded a run starts with
  about half the cached context, and Rupa's one-page CV cost $0.14 in total.
- **v1's verify comparison.** Under neutral checks nearly all v1 baseline
  PDFs pass, including page counts; "0 of 9 pass verify" was about Rupa's
  rules.
- **Wide-table claim.** v1's 40% compared Rupa and the baseline from two
  results folders. In v2, in one folder, Rupa cost 0.53× on `wide`.

## Limits

- The LLM judge is from the same model family as the agent and saw page
  images at 100 dpi. It disagreed with the human check on most content
  answers; the human sample is 15 pairs from one person.
- HTML outputs were printed to PDF for judging. Two baseline FAQ pages hid
  their answers in collapsed sections, which don't print, so the judge marked
  them partly complete; in a browser they work.
- Claude wrote the tasks and is also the agent under test.
- One person's tasks, Rupa's default theme only, list prices of October 2026.

## Seen in the runs, not fixed (Rupa is frozen)

- **Wide images run off the page.** Every Rupa PDF with an image (all 8
  lab reports, Opus and Sonnet) has the chart cut at the right edge: the
  supplied 900 px PNG is set at its natural 675 pt from a 58 pt margin, on a
  612 pt page, so the last data point and the right axis are gone. No
  baseline PDF has an image off the page. The theme has no rule shrinking an
  image to the text width, and `rupa verify`'s overflow check reads only
  text, so it passed all 8. Bench v2's own `in_bounds` check also reads only
  text and missed it; the LLM judge marked Rupa's lab layout 2 of 5 but
  never named the cut. Vajra found it in blind judging.
- A table split across a page break can leave one row under a repeated header
  at the top of the next page, and `rupa verify` passes it.
- The judge's most common layout complaint was large empty areas at page
  ends, where Rupa keeps a block whole rather than splitting it.

## Data

`bench/data-v2/runs.csv` (one row per run) and `summary.csv`, from
`uv run python bench/export.py --v2`. The analysis is
`uv run python bench/analyze_v2.py bench/results [--model ...]`. Raw results
folders, with every transcript, output, page image and judge verdict, are in
`bench/results/` on the machine that ran them.
