---
description: A plain request for a PDF triggers the skill, renders with rupa, and verifies.
tags: [outcome]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
expected_outcome: report.pdf exists, rendered by rupa from Markdown, then checked with rupa verify.
---

Write a 2-page PDF briefing on the AWS Well-Architected reliability pillar for my team. Save it as report.pdf in the current folder.
