## Command extension contribution

Adds `command.rupa`, an external, opt-in extension for [Rupa](https://github.com/VajraSarpa/rupa), a CLI that renders Markdown to HTML or PDF and checks the PDF. Two rules, each with its own permission, both at the review floor with the `local_write` risk class.

### What changed

- `command.rupa.force` (high): a render with `--force`. With `--to`, `-o` can name any path. If that file exists and isn't `.html` or `.pdf`, Rupa refuses unless `--force` is given, and then replaces it.
- `command.rupa.verify-out` (medium): `rupa verify PDF --out DIR`. It writes `verify.json` and sheet PNGs into a folder the caller picks, and deletes the sheets the previous `verify.json` there listed.
- Covers the `rupa` script (also `rupa.cmd`, `rupa.exe`) and launches through `uv run rupa`, `uvx rupa` (including `uvx --from git+…`) and `uv tool run rupa`.
- Risk class is `local_write`, as in `command.rwxmap`: both rules replace or delete local files and do nothing else. Risk tier matches severity.
- Files: the source, the portable fixture, the external trust binding, and the public descriptor written by `prepare_extension_contribution.py`.

### Upstream source and version

- Rupa [`v0.1.4`](https://github.com/VajraSarpa/rupa/tree/v0.1.4) (`7d6ad11`). I maintain Rupa.
- [`docs/cli-contract.md`](https://github.com/VajraSarpa/rupa/blob/v0.1.4/docs/cli-contract.md) lists what each command reads, writes and deletes. [`src/rupa/cli.py`](https://github.com/VajraSarpa/rupa/blob/v0.1.4/src/rupa/cli.py) is the parser.
- Render flags: `-o/--output` (required), `--to {html,pdf}`, `--theme`, `--pages`, `--force`, `--json`, `--version`. Verify flags: `--wants`, `--theme`, `--out`, `--sample`, `--json`.
- Both parsers use argparse with `allow_abbrev=False`, so `--forc` or `--ou` is a usage error (exit 2), not `--force` or `--out`.
- `verify` is the subcommand only when it is the first argument. `rupa ./verify -o out.pdf` renders a file named `verify`.
- Rupa makes no network calls and runs no subprocesses. It isn't on PyPI; the README installs it with `uv tool install git+https://github.com/VajraSarpa/rupa`.

### Capability boundary

- **Review:** `rupa … --force` and `rupa verify … --out DIR`, with the flag leading, trailing or after other options, `--output=x`, `-ox`, `--out=DIR`, quoted paths with spaces, and in `&&`, `;` and pipe chains.
- **Not matched:** a plain render, and `rupa verify PDF` without `--out` (sheets go to `<PDF>.verify/` beside the PDF).
- **Safe variants:** `--help`, `-h` and `--version` for the force rule; `--help` and `-h` for the verify rule. Argparse exits on them before anything is written.
- **Known limits:**
  - A plain `rupa in.md -o out.pdf` replaces an existing `.html` or `.pdf` without asking. It isn't matched: flagging it would review every normal run, the same call `command.rwxmap` made for runs without `--force`.
  - `rupa verify … --force` still matches the force rule, though Rupa rejects it (exit 2, nothing written). Guard compares arguments case-insensitively, so a `verify` safe variant would also clear `rupa VERIFY --force -o notes.txt`, which renders a file named `VERIFY` and overwrites `notes.txt`. A fixture case pins this.
  - `nohup rupa …` isn't unwrapped by Guard, so neither rule sees it. The unknown-command floor still reviews it.
  - Launcher options outside the listed set stop the `uvx` and `uv tool run` matchers (for example `uvx --refresh-package rupa …`). `uv run` follows unknown options conservatively.
  - Not covered: `rupa refs` (a maintainer command that writes reference PNGs), `python -m rupa` (doesn't exist), and the failure log Rupa appends to `~/.rupa/log.jsonl` on a non-zero exit.

### Fast validation

Built on hol-guard `main` at `101bc5f`, as a normal user (uid 30033) with Rust 1.88.0, bubblewrap 0.11.0 and `ssh-keygen`.

```sh
uv run --no-sync hol-guard extensions handoff --repo . \
  --source contributions/command-sources/command.rupa.json \
  --fixture tests/fixtures/command-source-rupa.v1.json
```

- `handoff`: "Contribution handoff is ready for command.rupa. Source, fixture, external trust mapping, and generated projections agree."
- `prepare_extension_contribution.py --check`: `ok: true`, `targetCommandsExecuted: 0`.
- Fixture: 83 of 83 cases pass, `target_commands_executed: 0` (57 force, 26 verify; 74 review, 5 block, 3 allow, 1 require-reapproval).
- `refresh_extension_artifacts.py --check-trust`: `authored_trust_complete: true`.
- `scripts/ci/verify_native_command_program.py`: ok, `stale_public_descriptors: []`, 163 generated files. It reads descriptors from the commit, so I ran it with the four files committed on a local branch.
- `cargo +1.88.0 fmt --all --check`: pass.
- `cargo +1.88.0 clippy --locked --workspace --all-targets -- -D warnings`: pass, 0 warnings.
- `cargo +1.88.0 test --locked --workspace --all-targets --no-fail-fast`: 13,678 passed, 5 failed, 39 ignored (89 binaries). None comes from this change. Four (`guard-command --lib`) fail the same with the `command.rupa` files removed; they depend on where the build container keeps `gh`, `uv` and `python3`, and the `uv` one passes once my `/usr/local/bin/uv` copy is moved aside. The fifth (`hol-guard-runtime` `workspace_inventory_op::recorded_python_vectors_match`) passes when run alone. Run with `CARGO_PROFILE_DEV_DEBUG=0` after the first build ran out of disk.
- Every case that claims something about Rupa's parser was also run against Rupa `v0.1.4` itself: 36 commands, exit codes and file changes as stated.

### Checklist

- [x] The source, fixture, and external trust-map entry use the same extension ID.
- [x] The canonical source, portable fixture, and external trust entry are included. I have not committed generated projections (command catalog, native program, baselines, digest vectors, directory render); maintainer automation regenerates them on `main` after merge.
- [x] Cases cover the intended destructive operations and their safe counterparts.
- [x] Optional public listing data contains no private email, secrets, or inferred claim authority.
- [ ] For a personal-fork PR, I enabled **Allow edits from maintainers** if I want Gitar to commit mechanical repairs. If GitHub says this also grants access to secrets, I left it disabled and will apply suggestions myself.
