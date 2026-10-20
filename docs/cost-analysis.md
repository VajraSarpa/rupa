---
title: What Rupa Costs
subtitle: Cost per document with the plugin, with Claude Code alone, and with Claude
author: Vajra Sarpa
date: 20 October 2026
toc: false
pages: 4
---

## Summary

On six document tasks it was never tuned on, Claude Code with the Rupa plugin produced each document for **$0.14 to $0.44**, against **$0.21 to $1.05** for Claude Code on its own: 42% cheaper on average, cheaper on every task, and about 1.9 times faster. Context saves more than cost: each document added about half as much to Claude's context window, and five documents in one session added 71% less (16,200 tokens against 55,300). In a blind check of 15 pairs, a person found the two documents equally good every time; an LLM judge preferred Claude Code's layout. The more Claude Code would iterate on its own layout, the bigger the saving.

Claude in the chat app was not measured. It builds a PDF the way Claude Code does without the plugin, by writing layout code, so expect baseline-like usage. It is billed by plan rather than per token, and Rupa doesn't run there today.

## How it was measured

Each run gave `claude -p` the same prompt in a fresh, empty folder, with the user's own plugins, skills and MCP servers switched off, five times per arm in a seeded interleaved order, on Claude Opus 5.5, 19 to 20 October 2026, with Rupa frozen at v0.1.3. The hypotheses and pass rules were registered before any run (`bench/PREREG.md`). Costs are what Claude Code reported, at API list prices.

- **Claude Code** (baseline): no plugin. Claude writes the HTML, CSS or PDF code and picks its own tools.
- **Claude Code, hinted**: the same, plus a three-line `CLAUDE.md` saying to write HTML with a print stylesheet, print it with headless Chrome and check the page count.
- **Rupa**: the plugin as tagged. Claude writes Markdown, renders it with `rupa`, then runs `rupa verify`.

## Cost per document

Medians of five runs each.

| Task | Claude Code | Hinted | Rupa | Time, Claude Code | Time, Rupa |
|---|---|---|---|---|---|
| One-page CV | $0.21 | $0.17 | $0.14 | 42 s | 24 s |
| Five-page lab report | $0.77 | $0.63 | $0.33 | 185 s | 76 s |
| Ten-page handbook | $0.51 | $0.56 | $0.39 | 140 s | 106 s |
| Two-page postmortem | $0.30 | $0.27 | $0.16 | 65 s | 27 s |
| HTML explainer | $0.22 | $0.21 | $0.18 | 50 s | 36 s |
| Report, then a revision | $1.05 | $1.15 | $0.44 | 142 s | 64 s |
| Average of the six | $0.51 | $0.50 | $0.27 | | |

Across the six tasks Rupa cost 0.58 times Claude Code alone (90% interval 0.55 to 0.63) and 0.62 times the hinted baseline (0.59 to 0.67). It took 0.54 times as long and added 0.51 times the context. The same benchmark on Rupa v0.1.2 gave 0.56 and 0.63, so the layout fixes in v0.1.3 cost nothing.

On the first benchmark's three tasks (15 to 16 October, three runs per arm), which Rupa had been tuned against, the saving was larger: $0.29 to $0.33 a document against $0.52 to $1.19, 40% to 74%. Those runs also loaded the machine's own plugins and skills into every session, which raised both arms' cost. Quote the held-out figure.

## Where the money goes

From the first benchmark's transcripts:

| Share of cost | Report, Claude Code | Report, Rupa | Guide, Claude Code | Guide, Rupa |
|---|---|---|---|---|
| Output (what Claude writes) | 33% | 21% | 44% | 27% |
| Cache reads (re-reading context each turn) | 19% | 14% | 18% | 10% |
| Cache writes (new context) | 48% | 65% | 37% | 63% |

- **Starting a session is most of a short run.** Claude Code writes its system prompt, tools and the skill to cache first. That is why the one-page CV saved only 7 cents, and why Rupa's cost moves less between tasks than Claude Code's.
- **Fewer output tokens.** Claude writes Markdown, not markup: 3,000 to 5,200 output tokens per Rupa run against 8,500 to 25,500 for Claude Code on the first benchmark.
- **Fewer turns where layout is hard.** Every turn re-reads the whole conversation. On the lab report Claude Code took 21 turns and Rupa 10; on the revision, 24 and 10. On short documents the turn counts are close, and the saving is smaller.

## The context window

For anyone on a Pro or Max plan, this is the saving that shows. A document's cost is paid once, but the context it adds stays for the rest of the session: every later turn re-reads it, and a fuller window gets compacted sooner. So the gap grows with each document.

Per document, the context added (the largest context in the run minus the session's starting context) was about half of Claude Code's: from 2,900 tokens for the CV to 12,000 for the handbook, against 5,000 to 26,500.

Over a session it was measured directly, on Rupa v0.1.2, three runs per arm: five documents in one session (three PDFs, an HTML page and a status note).

| Five documents, one session | Claude Code | Rupa | Less |
|---|---|---|---|
| Context added | 55,300 tokens | 16,200 tokens | 71% |
| Range across runs | 50,400 – 64,800 | 12,800 – 17,600 | |
| Turns | 37 | 19 | 49% |
| Cost | $4.52 | $1.88 | 58% |
| Time | 391 s | 153 s | 61% |

Not measured yet: sessions longer than five documents, how much later compaction comes, and whether output holds up better late in a long session.

## On a cheaper model

Measured on Claude Sonnet 5.5 with Rupa v0.1.2, three runs per arm on the same six tasks: Rupa cost 0.67 times Claude Code alone (90% interval 0.60 to 0.71) and 0.79 times the hinted baseline, and took 0.69 times as long. The saving keeps its direction with a smaller margin, because Sonnet took about as many turns with Rupa as without.

## On a subscription

With Claude Code on a Pro or Max plan there is no per-document bill; each document uses part of the plan's limits instead. If usage counts roughly in proportion to cost, which is an assumption, Rupa fits about 1.7 times as many documents into the same allowance.

## With Claude (the chat app)

Not measured. Asked for a PDF, Claude in the chat app writes and runs layout code in its sandbox, which is the same work the Claude Code baseline does, so it should land near the baseline's turns and tokens. Rupa can't help there yet: it is a local CLI plus a Claude Code plugin, and the chat sandbox would need the CLI and its PDF libraries installed.

## At volume

At API list prices, with the six held-out tasks in equal measure:

| Documents a month | Claude Code | Rupa | Saved |
|---|---|---|---|
| 10 | $5.13 | $2.73 | $2.40 |
| 50 | $25.63 | $13.63 | $12.00 |
| 200 | $102.50 | $54.50 | $48.00 |

## Quality

Every run in every arm made its document, and a per-item checklist scored Rupa's as complete as Claude Code's (0.97 against 0.97). In a blind check of 15 random pairs, I rated all 15 ties on content, design and ease of reading. An LLM judge shown the same pairs preferred Claude Code's document in most of them, mainly for page balance and Rupa's plainer theme, and agreed with me on 2 of 30 answers. The pre-registered quality rule used that judge, so it fails. Rupa's documents hold somewhat fewer words (0.88 times on these tasks), because the theme keeps its margins and type size.

## What finding out cost

Both benchmarks and the rerun took 401 runs and $178.73 at list price, plus $28.35 for the LLM judge. At the held-out saving of about $0.24 a document, that pays back after nearly 900 documents. The cost of the build sessions themselves isn't included.

## Limits of these numbers

- Five runs per arm on one model for the headline, one person's tasks, written by Claude, the default theme only. Agent runs vary, so the medians matter more than any single run.
- The human check is one person and 15 pairs, given as one verdict for the set.
- Prices are list prices as of October 2026.
