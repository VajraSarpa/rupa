---
description: A request for a web page triggers the skill and renders HTML with rupa instead of hand-written markup.
tags: [outcome]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
expected_outcome: dns.html exists, rendered by rupa from Markdown, with no hand-written CSS file.
---

Make a one-page HTML explainer of how DNS resolution works, from typing a URL to getting an IP address. Save it as dns.html here.
