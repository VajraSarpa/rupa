---
name: render
description: Use when the user wants an HTML page or PDF document. Write Markdown, render it with the rupa CLI, then verify the PDF. Never hand-write HTML, CSS, or PDF code.
---

# Rendering with Rupa

## Render

1. Write the content as Markdown. Optional frontmatter keys: `title`,
   `subtitle`, `author`, `date`, `theme`, `toc` (true/false), `pages`.
   No other keys. If the user asks for a page count, set `pages: N`: Rupa
   then fits the PDF to N pages itself (drops the contents list, tightens
   type). Plan about 30 lines per page: a line of prose is about 15 words,
   and each code line, table row, list item and heading is one line.
2. Use `#` for parts, `##` for sections, `###` for subsections.
   Fenced code blocks take a language tag. Images are relative paths to
   files next to the Markdown file (or `data:image` URIs), never URLs.
3. Render with one command, using the extension the user asked for:

   ```bash
   rupa draft.md -o out/report.pdf
   ```

4. Read only the one-line status. Do not open or print the output file.
5. On a non-zero exit, fix the Markdown: `3` bad input and `4` render
   failure explain themselves on stderr; `5` means the PDF is still over
   `pages` and the status line says about how many lines to cut. Cut that
   many, all in one turn (rewrite the file or send every edit together),
   and render again. Do not measure pages yourself.

## Verify (PDF)

1. Run `rupa verify out/report.pdf` (add `--wants wants.yaml` if the project
   has one). It prints one line and writes `verify.json` plus sheet images.
2. If the status line reports no sheets, the PDF passed: skip to step 6.
   Do not render or open page images yourself.
   Otherwise read `verify.json`, then open each sheet image listed under `sheets`.
   Each sheet shows the theme's reference page on the left and the rendered
   page on the right.
3. Judge every sheet against each item in `rubric`. Record one line per
   sheet: `p<N> <kind>: PASS` or `p<N> <kind>: FAIL <rubric item> - <what>`.
4. Fix failures in the Markdown only: split a wide table, shorten a long
   code line, move or trim content around an awkward break. Then render and
   verify again. Stop after two fix rounds.
5. If a failure can only be fixed in the theme (CSS), do not edit CSS.
   Report it to the user as a theme issue.
6. Tell the user the final check line and your per-sheet verdicts in a few
   lines.

Do not add styling to the Markdown. A different look is a theme change.
