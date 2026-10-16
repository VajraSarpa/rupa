# Rupa

A renderer layer for Claude Code. Claude writes Markdown; Rupa owns the form
and turns it into a styled HTML page or PDF, then helps check the result.

*Rūpa* is Sanskrit for "form".

```bash
uv tool install .
echo "# Hello" | rupa -o hello.pdf
# rupa: wrote hello.pdf (pdf, 1 page, 9,812 bytes)
rupa verify hello.pdf
# verify: 8/8 checks pass; 2 sheets for visual review in hello.verify/
```

## Why

When Claude Code makes a document by hand, it writes every tag and CSS rule,
hunts for a PDF tool, and debugs the render. Each of those is a turn, and every
turn re-reads the whole conversation. Rupa takes the form work out of the loop:
Claude writes content, Rupa applies a tested theme and prints one status line.

## What's here

| Path | What it is |
|---|---|
| `src/rupa/` | The CLI: `rupa` (render), `rupa verify` (check a PDF), `rupa refs` (rebuild reference pages) |
| `src/rupa/themes/` | Theme CSS. PDF text is forced to solid black |
| `src/rupa/references/` | Reference pages each theme is visually compared against |
| `plugin/` | Claude Code plugin: one skill that renders, verifies and reviews |
| `plugin/evals/` | `claude plugin eval` suite: does the skill trigger, render with rupa, and pass verify |
| `bench/` | Three-arm benchmark (baseline, Rupa, Rupa + verify) and a fake `claude` for testing it |
| `docs/` | Plan, guide and tutorial: Markdown source, build script, rendered PDF and HTML |
| `wants.example.yaml` | Every verification rule, with its default |

## Contract

- **stdin or a file:** Markdown with optional YAML frontmatter
- **`-o PATH`:** the rendered file, format from the extension
- **stdout:** one status line, never the document
- **exit codes:** `0` ok, `2` usage, `3` bad input, `4` render failure, `5` verify checks failed

## Verification

`rupa verify` runs code checks on the PDF (color, page size, page count, empty
or sparse pages, stranded headings, overflow). It also writes side-by-side
sheets, reference page | rendered page, for every flagged page plus one page of
each type. The plugin's skill has Claude review those sheets against a rubric
and fix the Markdown. Rupa never calls a model itself.

## Use it from Claude Code

```bash
uv tool install .                  # puts rupa on PATH
claude plugin validate ./plugin
claude --plugin-dir ./plugin
```

Then ask for a PDF. The `rupa:render` skill takes it from there.

## Develop

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and Pango for WeasyPrint
(`sudo apt install libpango-1.0-0 libpangoft2-1.0-0`, or `brew install pango`).

```bash
uv sync
uv run pytest -q                   # 40 tests
uvx ruff check src tests
uv run rupa refs                   # after any theme change; commit the PNGs
uv run python docs/build.py        # re-render the guide with Rupa
```

## Status

Working prototype. The token benchmark hasn't been run yet. Start with the
pilot, `bench/bench.sh` (one run per arm, roughly $1–2); see the guide's
"Measuring the savings" section.

## License

MIT
