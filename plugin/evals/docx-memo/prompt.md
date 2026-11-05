---
description: A request for a Word document triggers the skill and renders DOCX with rupa instead of hand-written python-docx or pandoc.
tags: [outcome]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
expected_outcome: memo.docx exists, rendered by rupa from Markdown, with no python-docx or pandoc script.
---

Write a one-page Word memo to my team proposing we move our nightly batch jobs from cron on EC2 to EventBridge Scheduler. Save it as memo.docx here.
