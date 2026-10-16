---
description: Content that is hard to lay out (a wide table, long code lines) still ends in a PDF that passes rupa verify.
tags: [outcome]
max_turns: 50
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
expected_outcome: compute.pdf exists and a rupa verify in the run reports every check passing.
---

Make a PDF called compute.pdf comparing EC2, Lambda, Fargate, App Runner, Lightsail and Batch. Include one table with these columns: service, unit of compute, max runtime, scaling model, cold starts, pricing basis, state, typical use, and when to avoid it. Also include a short Python boto3 snippet that starts each service. Make sure it looks right before you finish.
