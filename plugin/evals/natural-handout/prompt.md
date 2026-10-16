---
description: Natural phrasing ("printable handout") with no file format named still triggers the skill.
tags: [trigger]
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: The render skill is invoked. Producing the file needs the outcome grants, so only the trigger is graded here.
---

Turn these meeting notes into a clean printable handout for Thursday's team meeting:

- Q3 on-call load down 18% after the runbook rewrite
- Two incidents, both config drift; drift detection ships next sprint
- Proposal: move the weekly review to Tuesdays
- Owners: Sam (drift detection), Priya (runbook upkeep)
