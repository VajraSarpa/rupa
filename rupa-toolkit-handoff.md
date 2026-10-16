# Handoff: Claude Code's built-in tools, mapped to Rupa

Reference for working on Rupa (`~/Projects/rupa`) in Claude Code. Checked
against the Claude Code docs and CLI v2.1.301 on 2026-10-15. Commands can
change between versions: run `claude --version`, and if something here is
missing, check `/help` or the docs before assuming it exists.

**For Claude Code reading this:** treat it as a menu, not a task list. Don't
install plugins, change settings or run anything that spends tokens (evals,
benchmark, ultrareview) without asking me first. Free checks (tests, lint,
validate, details) are fine to run.

## Project facts

- Python 3.11+ CLI, managed with `uv`. Tests: `uv run pytest -q` (42).
  Lint: `uvx ruff check src tests`.
- Commands: `rupa` (render Markdown to HTML/PDF), `rupa verify` (check a PDF,
  write review sheets), `rupa refs` (rebuild a theme's reference pages).
- Plugin in `plugin/`: one skill, `rupa:render`, plus a SessionStart hook.
- Eval suite in `plugin/evals/`; benchmark in `bench/`; guide in `docs/`.

## 1. Plugin development (CLI, run in a shell)

| Command | What it does | Use on Rupa |
|---|---|---|
| `claude plugin validate ./plugin` | Checks manifest, skills, hooks for schema errors | After any edit to `plugin/` |
| `claude plugin details rupa` | Lists components and **projected token cost** | Confirms the skill stays cheap in context (needs the plugin installed or loaded) |
| `claude --plugin-dir ./plugin` | Loads the plugin for one session without installing | Manual testing |
| `/reload-plugins` | Reloads plugins inside a running session | After editing `SKILL.md` mid-session |
| `claude plugin eval .` (from `plugin/`) | Runs `evals/` with and without the plugin, scores both | **Costs tokens.** See `plugin/evals/README.md`; start with `--tag trigger --runs 1` |
| `claude plugin eval init` | Interviews you and writes new eval cases | Adding cases later |
| `claude plugin tag ./plugin` | Creates a `rupa--v<version>` git tag after checking `plugin.json` | Releases |

## 2. Skills (inside a session)

| Command | What it does | Use on Rupa |
|---|---|---|
| `/skills` | Lists skills; press `t` to sort by token count | Check `rupa:render`'s context cost |
| `/skill-doctor` | Shows each skill's context cost and how often it's used (v2.1.252+) | Is the description cheap, and does it trigger? |
| skill-creator plugin | Iterate on one skill with its own eval format | Optional; overlaps `claude plugin eval`, and the two don't share case files |

## 3. Code quality (bundled skills and commands)

| Command | What it does | Use on Rupa |
|---|---|---|
| `/code-review` (alias `/review`) | Reviews the current diff, a branch, PR or path for bugs. Effort levels `low` to `max`; `--fix` applies fixes | Before each commit or PR |
| `/code-review ultra` (alias `/ultrareview`) | Deep multi-agent review in a cloud sandbox | **Costs more.** Before going public |
| `/security-review` | Reviews your branch's diff vs `origin`'s default branch for security issues | Needs the GitHub remote first. Relevant: Rupa blocks remote fetches and escapes raw HTML |
| `/simplify` | Four agents review changed code for reuse, simplification, efficiency | After a feature lands |
| `/verify` | Builds and runs the app to confirm a change works, rather than trusting tests | Render a sample and look at the result |
| `/diff` | Shows the working-tree changes, including Claude's edits | Before committing |

## 4. Code intelligence

`pyright-lsp` from the official marketplace gives Claude live type errors after
each edit and symbol navigation.

```bash
uv tool install pyright              # provides pyright-langserver
```

Then in a session: `/plugin install pyright-lsp@claude-plugins-official`.
Terminal sessions only; it doesn't run in cloud sessions.

## 5. Official plugins worth a look

Browse with `/plugin` → **Discover**. Install as
`/plugin install <name>@claude-plugins-official`. Anthropic maintains these:

- `commit-commands`: commit and PR workflow helpers
- `security-guidance`: catches security issues as Claude writes code
- `feature-dev`: structured feature development workflow
- `code-review`: also bundled as `/code-review`; you likely don't need both

## 6. Context, cost and sessions

| Command | Use on Rupa |
|---|---|
| `/context` | See what's filling the context window; check the plugin's footprint |
| `/usage` (alias `/cost`) | Session cost and plan limits; check after eval or benchmark runs |
| `/insights` | HTML report on your recent sessions: where things go wrong |
| `/compact` | Free context on long sessions |
| `/rewind` (alias `/undo`) | Roll back conversation and code to a checkpoint |
| `/doctor` | Install health, PATH problems, unused plugins and skills |
| `claude -p "..." --output-format json` | Headless run with `usage` and `total_cost_usd`; what `bench/bench.sh` uses |

## 7. Project setup

| Command | Use on Rupa |
|---|---|
| `/init` | Writes a `CLAUDE.md`. Worth it: record test/lint commands, "never hand-write HTML/CSS", "run `rupa refs` after theme changes" |
| `/memory` | Edit `CLAUDE.md` and auto memory |
| `/permissions` | Allow `uv run pytest`, `uvx ruff`, `rupa` without prompts |
| `/fewer-permission-prompts` | Scans past sessions and proposes an allowlist for `.claude/settings.json` |
| `/hooks` | View hooks. Candidate: a project PostToolUse hook that runs `uvx ruff format` after Python edits |
| `/sandbox` | Toggle the sandboxed Bash tool |
| `/statusline` | Configure the status line |

## Suggested order for the next session

1. Free: `uv run pytest -q`, `uvx ruff check src tests`,
   `claude plugin validate ./plugin`.
2. `/init` to create `CLAUDE.md` with the project facts above.
3. Install `pyright-lsp` (ask first).
4. Push to GitHub; then `/security-review` and `/code-review` on the repo.
5. Ask before spending: `claude plugin eval . --tag trigger --runs 1` from
   `plugin/` (about $0.25), then the benchmark pilot `bench/bench.sh`
   (about $1–2).

Sources: code.claude.com/docs/en/commands, /plugin-evals,
/plugins/anthropic-marketplaces, /plugins/code-intelligence,
/plugins/manifest-reference.
