# Rupa plugin evals

Six cases for `claude plugin eval`. Each case runs with the plugin and again
without it (the no-plugin baseline), three times per arm by default.

| Case | Tag | Checks |
|---|---|---|
| `pdf-report` | outcome | Skill fires, `report.pdf` made by `rupa`, then `rupa verify`; no hand-written HTML/CSS; reply reports the result (judge) |
| `html-page` | outcome | Skill fires, `dns.html` made by `rupa`, no `.html`/`.css` written by hand |
| `wide-table-fix-loop` | outcome | Hard layout still ends in a PDF whose last verify passes, in at most three renders (two fix rounds) |
| `natural-handout` | trigger | "Printable handout" with no format named still fires the skill |
| `no-trigger-pdf-question` | trigger | A question about PDFs does not fire the skill |
| `no-trigger-code` | trigger | An ordinary coding request does not fire the skill |

## Before running

`rupa` must be on PATH for the outcome cases. Runs that use Bash execute in
Claude Code's sandbox, where the home directory is unreadable, so install
`rupa` outside your home directory:

```bash
UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install .
```

Linux also needs `bubblewrap` and `socat` for the sandbox.

## Running

Cheapest first: the trigger cases need no tool grants and no Bash.

```bash
cd plugin
claude plugin eval . --tag trigger --runs 1          # 3 cases x 1 run x 2 arms
```

Then the outcome cases. They need Write, Edit and Bash. Grant Bash broadly so
the baseline arm can try its own way to make a PDF; otherwise the comparison
is rigged.

```bash
claude plugin eval . --tag outcome --allow-tools Write Edit Bash --max-cost-usd 15
```

Iterating on one case: `--case pdf-report --runs 1 --ablation none`.

## Reading the results

- `Δ` near zero with `skill-fired` failing: Claude isn't choosing the skill on
  natural phrasing. Fix the `description` in `skills/render/SKILL.md`.
- `skill-fired` and `tool_used Skill` graders are reported but not scored in
  two-arm runs, since they can never pass without the plugin.
- The `no-trigger` cases score both arms on purpose (`arm: both`).
- Results go to `evals/results/`, which is git-ignored.

These cases measure whether Rupa works. Whether it saves turns and cost is
`bench/bench.sh`'s job.
