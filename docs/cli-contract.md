# Rupa CLI contract

What each `rupa` command reads, writes, deletes and reaches, as of `v0.1.4`.
The README's [Contract](../README.md#contract) section covers stdout and exit
codes for the plugin; this page is for anyone who wraps or polices the
commands, such as a pre-execution policy check.

## Commands

| Command | Reads | Writes | Deletes | Network |
|---|---|---|---|---|
| `rupa [INPUT] -o OUT` | `INPUT` (a Markdown file, or stdin when `INPUT` is `-` or absent); images it names, from inside `INPUT`'s folder (cwd for stdin); the bundled themes and fonts | `OUT`, creating its parent folders | Nothing | None |
| `rupa verify PDF` | `PDF`; `--wants` file if given; the theme's bundled reference pages | `<PDF minus extension>.verify/`, or `--out DIR`: `verify.json` and `sheet-p<NNN>-<kind>.png` files, created or replaced | The sheets the previous `verify.json` in that folder listed, and only those | None |
| `rupa refs` | The bundled `references/sample.md`, themes and fonts | `cover.png`, `prose.png`, `table.png`, `code.png` in `--out DIR`, created or replaced | Nothing | None |

Every command that exits non-zero or crashes also appends one line to
`~/.rupa/log.jsonl` (mode 0600; past 1 MB it is moved to `log.jsonl.1`,
replacing the old one). `RUPA_LOG=<path>` moves the log and `RUPA_LOG=off`
stops it. Successful runs write no log.

### Flags

- `rupa`: `-o/--output` (required), `--to {html,pdf}`, `--theme`, `--pages N`,
  `--force`, `--json`, `--version`. Without `--to` the format comes from
  `OUT`'s extension, so `OUT` must end in `.html` or `.pdf`.
- `rupa verify`: `--wants FILE`, `--theme`, `--out DIR`,
  `--sample {per-type,flagged,all,none}`, `--json`.
- `rupa refs`: `--theme`, `--out DIR`.

## Risky surfaces

- **`rupa -o OUT` replaces `OUT` without asking** when it already exists as
  `.html` or `.pdf`.
- **`rupa --to FMT -o OUT` can name any path.** If `OUT` exists and isn't
  `.html` or `.pdf`, Rupa refuses (exit 2) unless `--force` is given, and
  then it replaces that file. `--to html --force -o notes.txt` overwrites
  `notes.txt`.
- **`rupa verify --out DIR` writes into a folder the caller chooses.** It
  replaces `verify.json` and any sheet with the same name there, and deletes
  the sheets the old `verify.json` listed (names must match
  `sheet-p<digits>-<word>.png`; nothing else is touched).
- **`rupa refs` is a maintainer command**, and is out of scope for policy
  descriptors. In a source checkout without `--out` it rewrites
  `src/rupa/references/<theme>/`; an installed copy refuses to run without
  `--out` (exit 2).

Rupa never fetches from the network, never runs a subprocess, and never
passes raw HTML through. An image must be a relative path inside the input's
folder (not hidden, an image extension, bytes that decode) or a `data:image`
URI; anything else fails the run (exit 3 or 4).

## Exit codes

`0` ok, `2` usage, `3` bad input (including a missing PDF to verify or an
unwritable verify folder), `4` render failure, `5` verify checks failed or a
PDF still over its page budget. A crash is exit `1`.

## Stability

- `-o`, `--to`, `--force`, `--theme`, `--pages`, `--json` and the `verify`
  and `refs` subcommand names are never renamed or given a new meaning.
- **Flags must be spelled in full.** Since `v0.1.4` an abbreviation such as
  `--forc` or `--outp` is a usage error (exit 2), so a policy check that
  matches `--force` or `--out` sees every spelling Rupa accepts. Up to
  `v0.1.3`, argparse's prefix matching accepted any unambiguous abbreviation.
- **New output formats are additive.** Slides, the next planned format, will
  arrive as a new `--to` value (for example `--to slides`) or a new
  subcommand, never by changing what an existing flag or value does.
- A change to anything on this page is listed in the release notes.
