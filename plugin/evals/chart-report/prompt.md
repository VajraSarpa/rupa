---
description: A request for a report with a chart triggers the skill and draws the chart with a vega-lite block, not plotting code.
tags: [outcome]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
expected_outcome: sales.pdf exists, rendered by rupa from Markdown holding a vega-lite chart; no matplotlib or Altair script was run.
---

Quarterly sales were Q1 $120k, Q2 $135k, Q3 $128k, Q4 $162k. Make a one-page PDF for my manager with a bar chart of the quarters and two sentences on the trend. Save it as sales.pdf here.
