---
type: tool_order
before: { tool: Bash, input_match: '\brupa\b[^"]*-o[^"]*\.pdf' }
after: { tool: Bash, input_match: '\brupa verify\b' }
arm: with-only
---
