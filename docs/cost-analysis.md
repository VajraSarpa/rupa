---
title: What Rupa Costs
subtitle: Cost per document with the plugin, with Claude Code alone, and with Claude
author: Vajra Sarpa
date: 16 October 2026
toc: false
pages: 3
---

## Summary

On three real document tasks, Claude Code with the Rupa plugin produced each PDF for **$0.29 to $0.33**, against **$0.52 to $1.19** for Claude Code on its own: 40% to 74% cheaper, and 2.4 to 5.6 times faster. Each document also added 61% to 86% less to Claude's context window. Every Rupa PDF passed `rupa verify`; no baseline PDF did. The harder the layout, the bigger the saving.

Claude in the chat app was not measured. It builds a PDF the way Claude Code does without the plugin, by writing layout code, so expect baseline-like usage. It is billed by plan rather than per token, and Rupa doesn't run there today.

## How it was measured

Each run gave `claude -p` the same prompt in a fresh, empty folder, three times per arm, on Claude Opus 5.5, 15 to 16 October 2026. Costs are what Claude Code reported, at API list prices.

- **Claude Code** (baseline): no plugin. Claude writes the HTML, CSS or PDF code and picks its own tools.
- **Rupa**: the plugin as shipped. Claude writes Markdown, renders it with `rupa`, then runs `rupa verify`.

Prices used to split the cost, per million tokens: input $4, output $20, cache write $8 (Claude Code caches for an hour), cache read $0.20. They reproduce the reported cost of a run to the cent.

## Cost per document

Medians of three runs each.

| Task | Claude Code | Rupa | Saving | Time, Claude Code | Time, Rupa |
|---|---|---|---|---|---|
| Two-page report | 13 turns, $0.52 | 7 turns, $0.29 | 45% | 112 s | 36 s |
| Three-page guide | 23 turns, $1.19 | 6 turns, $0.31 | 74% | 252 s | 45 s |
| Wide table (11 columns) | 11 turns, $0.54 | 6 turns, $0.33 | 40% | 124 s | 52 s |
| Average of the three | $0.75 | $0.31 | 59% | 163 s | 44 s |

Runs vary. Baseline guide runs cost between $0.85 and $1.28 across separate days, and Rupa runs between $0.31 and $0.45, so read the guide saving as 60% to 75%.

## Where the money goes

| Share of cost | Report, Claude Code | Report, Rupa | Guide, Claude Code | Guide, Rupa |
|---|---|---|---|---|
| Output (what Claude writes) | 33% | 21% | 44% | 27% |
| Cache reads (re-reading context each turn) | 19% | 14% | 18% | 10% |
| Cache writes (new context) | 48% | 65% | 37% | 63% |

- **A floor of about $0.19.** Starting a session writes the system prompt, tools and skill to cache, roughly 23,000 tokens. That is most of a Rupa run, and it is why Rupa's cost barely moves between tasks.
- **Fewer output tokens.** Claude writes Markdown, not markup: 3,000 to 5,200 output tokens per Rupa run against 8,500 to 25,500 for Claude Code.
- **Fewer turns.** Every turn re-reads the whole conversation. Claude Code spends turns fixing its own layout; Rupa's page budget and verify checks settle most of that in one render.

## The context window

Rupa also leaves more room in the conversation. Measured from each run's transcript, here is the context a document added (the largest context in the run minus the session's starting context):

| Task | Claude Code | Rupa | Less |
|---|---|---|---|
| Two-page report | 12,220 tokens | 3,785 tokens | 69% |
| Three-page guide | 34,308 tokens | 4,849 tokens | 86% |
| Wide table | 14,927 tokens | 5,779 tokens | 61% |
| Average of the three | 20,485 tokens | 4,804 tokens | 77% |

That context stays for the rest of the session: every later turn re-reads it, and a full window gets compacted sooner. Five guides in one session would add about 172,000 tokens without Rupa, 17% of Opus 5.5's million-token window, and about 24,000 with it, 2.4%. The reason is the same as for cost: Rupa returns one status line instead of the document, and Claude doesn't write or re-read markup.

## On a cheaper model

Priced at Claude Sonnet 5.5 rates ($2 input, $10 output, $4 cache write, $0.20 cache read), the same token counts would cost about $0.16 to $0.18 per Rupa document and $0.29 to $0.70 per Claude Code document. The saving keeps its shape. This is arithmetic, not a measurement: Sonnet may take a different number of turns.

## On a subscription

With Claude Code on a Pro or Max plan there is no per-document bill; each document uses part of the plan's limits instead. If usage counts roughly in proportion to tokens, which is an assumption, Rupa fits about two and a half times as many documents into the same allowance, and finishes each one in under a minute.

## With Claude (the chat app)

Not measured. Asked for a PDF, Claude in the chat app writes and runs layout code in its sandbox, which is the same work the Claude Code baseline does, so it should land near the baseline's turns and tokens. On a plan it is not billed per document. Rupa can't help there yet: it is a local CLI plus a Claude Code plugin, and the chat sandbox would need the CLI and its PDF libraries installed. Measuring it properly would mean running the same tasks through the API with the code execution tool.

## At volume

At API list prices, with the three tasks in equal measure:

| Documents a month | Claude Code | Rupa | Saved |
|---|---|---|---|
| 10 | $7.53 | $3.07 | $4.46 |
| 50 | $37.65 | $15.37 | $22.28 |
| 200 | $150.60 | $61.47 | $89.13 |

## What finding out cost

The benchmarks took 101 runs and $46.30 in tokens. At an average saving of about $0.45 a document, that pays back after roughly a hundred documents. The cost of the build sessions themselves isn't included.

## Limits of these numbers

- Three runs per arm, one model and one person's tasks. Agent runs vary, so the medians matter more than any single run.
- The baseline PDFs fail verify partly by Rupa's own definition (pure black text, Rupa's margins). They were readable; they weren't held to the same check.
- Prices are list prices as of October 2026.
