---
description: A question that mentions PDF but asks for no document must not trigger the skill.
tags: [trigger]
max_turns: 5
allowed_tools: [Read, Skill]
expected_outcome: A short answer in the reply; the render skill is never invoked.
---

What's the difference between PDF/A and a regular PDF? Two or three sentences is plenty.
