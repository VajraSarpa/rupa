# `command.rupa`: build report (2026-11-03)

A Claude Code cloud session built and checked the `command.rupa` HOL Guard Command extension in its own container. It cloned `hashgraph-online/hol-guard` read-only and pushed, forked and opened nothing upstream. The four files in this folder sit at the paths they'd have in hol-guard; `pr-body.md` is the PR description. Log paths below were inside that container and no longer exist.

## hol-guard commit

`101bc5f97adb4dc824c2542d806f5f9989f23839`, `main` at 2026-11-03 04:48 UTC ("feat(command): add Cross Exam coverage with terminator-aware stdio", committed 2026-11-02 23:03 -05:00).

## Setup

Done as root, then everything else as user `guardtest`, following [nonroot-test-run.md](../nonroot-test-run.md).

| Step | Result | Time |
|---|---|---|
| `useradd -m guardtest`; `id -u` | 30033 (not 0) | — |
| `umask 022` in guardtest's `~/.guardenv`, sourced from `.profile` and `.bashrc` | `umask` prints `0022` in every run | — |
| Proxy settings and CA bundle copied into guardtest's env | ok | — |
| `apt-get install openssh-client` | `/usr/bin/ssh-keygen` | ~20s |
| bubblewrap 0.11.0 built from the release tarball with meson, installed as `/usr/bin/bwrap` (no bwrap was installed before) | `bubblewrap 0.11.0` | ~1m |
| uv: root's binary copied to `/usr/local/bin` | ok | — |
| rustup: root's binary copied as `rustup-init`, then `rustup toolchain install 1.88.0 --profile minimal --component rustfmt --component clippy` | cargo 1.88.0, rustfmt 1.8.0, clippy 0.1.88 | 23s |
| `git clone https://github.com/hashgraph-online/hol-guard ~/hol-guard` (under home, not `/tmp`) | ok | 44s |
| `uv sync --extra dev --frozen --python 3.12` | ok | 19s |
| `cargo +1.88.0 build --locked --manifest-path rust/Cargo.toml --release -p guard-command -p hol-guard-runtime --bin guard-command-source --bin hol-guard-runtime` | ok | 22m00s |

## Reading done first

- PRs #6259 (`command.rwxmap`, merged 2026-10-31 as `ce949cd`) and #5911 (`command.ccx`, merged 2026-10-31 as `cff79d5`): their four files from the merge commits, and their PR pages. `gh pr view` couldn't run here: GraphQL is blocked for this session, and the REST API refuses repositories not attached with push credentials, which I didn't request. I read the PR bodies and review threads through a web fetch instead, which returns a summary rather than verbatim text.
- `CONTRIBUTING.md`, `docs/guard/extensions/contributing.md`, `docs/guard/extension-contributions.md` and `.github/PULL_REQUEST_TEMPLATE/command-extension.md` at `101bc5f`.
- Rupa `v0.1.4` (`7d6ad11`): `src/rupa/cli.py`, `docs/cli-contract.md`, and `rupa --help` / `rupa verify --help` from `uvx --from git+https://github.com/VajraSarpa/rupa@v0.1.4 rupa`.

## Commands run, as guardtest in `~/hol-guard`

The source, trust binding and fixture were written by small scripts, so the fixture always embeds the exact source. The trust binding came from their script, not by hand.

| Command | Result | Time |
|---|---|---|
| `uv run --no-sync python scripts/refresh_extension_artifacts.py --trust-only` | `trust binding: added command.rupa as external`; `{"ok": true, "trust_map_changed": true}` | <5s |
| Fixture through `guard-command-source test`, using the same `authoring_request(..., development=_development_release)` call `prepare` makes | **83 / 83 pass**, `ok: true`, `target_commands_executed: 0`, program digest `3ad83d60…` | ~30s |
| `uv run --no-sync python scripts/prepare_extension_contribution.py --compiler rust/target/release/guard-command-source --source contributions/command-sources/command.rupa.json --fixture tests/fixtures/command-source-rupa.v1.json` | `{"checked": false, "fixtures": ["tests/fixtures/command-source-rupa.v1.json"], "ok": true, "targetCommandsExecuted": 0}`; wrote `contributions/extensions/command.rupa.json` | 29s |
| Same with `--check` | `{"checked": true, ..., "ok": true, "targetCommandsExecuted": 0}` | 31s |
| `uv run --no-sync hol-guard extensions handoff --repo . --source contributions/command-sources/command.rupa.json --fixture tests/fixtures/command-source-rupa.v1.json` | "Contribution handoff is ready for command.rupa. Source, fixture, external trust mapping, and generated projections agree. No target was executed and active protection was not changed." | 48s (297s on the first run, cold) |
| `uv run --no-sync python scripts/refresh_extension_artifacts.py --check-trust` | `{"authored_trust_complete": true, "ok": true}` | 0s |
| `uv run --no-sync python scripts/ci/verify_native_command_program.py --compiler rust/target/release/guard-command-source`, files untracked | **fail**, by design: `"stale_public_descriptors": ["contributions/extensions/command.rupa.json"]`. Its first step compares descriptor bytes in git `HEAD`, and the descriptor wasn't committed. The expected descriptor it printed is identical to the one `prepare` wrote. | 17s |
| Same, with the four files committed on a throwaway local branch (`git switch -c local-rupa-check`, commit, run, `git switch main`, `git branch -D`). Never pushed; the files were then restored from these copies. | **pass**: `"ok": true, "stale_public_descriptors": []`; program build and `--check` both ok, 163 generated files, program digest `5a43969a…`, catalog `eae1a9b5…` | 46s |
| `git status --short` | only the four files, untracked | — |
| `cargo +1.88.0 fmt --manifest-path rust/Cargo.toml --all --check` | **pass** | 32s |
| `cargo +1.88.0 clippy --locked --manifest-path rust/Cargo.toml --workspace --all-targets -- -D warnings` | **pass**, 0 warnings | 5m51s |
| `cargo +1.88.0 test --locked --manifest-path rust/Cargo.toml --workspace --all-targets --no-fail-fast` (first attempt) | **couldn't finish**: the session's disk allowance ran out while building the debug test binaries (14 GB `target/debug`); 0 test binaries ran | ~10m |
| Same, after deleting `target/debug`, with `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0` | **fail**: 13,678 passed, **5 failed**, 39 ignored, across 89 test binaries. Targets that failed: `-p guard-command --lib` (4), `-p hol-guard-runtime --lib` (1). Details below. | 43m02s |
| The 4 `guard-command` failures, with the four rupa files moved out of the checkout and the trust map regenerated | **same 4 fail** | ~3m (incl. rebuild) |
| `hol-guard-runtime` `workspace_inventory_op::tests::recorded_python_vectors_match` alone, with and without the rupa files | **pass** both times | <1m |
| `tests_listing_find_probes::version_probes_admit_lone_flags_and_keep_npx_review` alone, with my `/usr/local/bin/uv` and `uvx` moved aside | **pass** | <1m |
| `prepare_extension_contribution.py --check` and `extensions handoff` again, on the restored files | both **pass** (same output as above) | 38s, 6m01s |

The cargo gate ran once more than this table shows: I stopped a first run after fmt when I found that Rust tests read the command sources and fixtures, so the gate has to run on the final files. The table is the run on the final files.

### The five test failures

None comes from `command.rupa`. As the dry run did, I report them and haven't touched their code.

| Test | Failure | Why I think it's this container |
|---|---|---|
| `guard-command` `pretool::repo_create_reason::tests::the_private_alternative_runs_without_review` | `assert_ne!` got `allow` for `/usr/local/bin/gh repo create todo-app --private …` | This image ships `gh` in `/usr/local/bin`. Fails the same with the rupa files removed. |
| `guard-command` `pretool::tests_listing_find_probes::version_probes_admit_lone_flags_and_keep_npx_review` | panics on `/usr/local/bin/uv --version` | I copied `uv` into `/usr/local/bin` during setup, as nonroot-test-run.md did. Passes with that copy moved aside. |
| `guard-command` `restricted_pytest::venv::tests::a_workspace_venv_grants_the_install_its_launchers_run` | expected `Some("/usr/bin")`, got `None` | Host interpreter layout. Fails the same with the rupa files removed. |
| `guard-command` `sfrs_interpreter_vectors::interpreter_helpers_match_recorded_python` | 8 `python_interpreter_trust` vectors give `trusted_system` where `user_controlled` was recorded, for `/usr/local/bin/python3` | This image's `python3` lives in `/usr/local/bin`. Fails the same with the rupa files removed. |
| `hol-guard-runtime` `workspace_inventory_op::tests::recorded_python_vectors_match` | `rust_go` inventory had `version: null` where `1.0.200` was recorded | Passes on its own, with and without the rupa files. Looks like a timing or load effect in the full run. |

nonroot-test-run.md got 0 failures on `2dc9e9a` in a similar setup. Main has moved 1,005 commits since then (76 test binaries then, 89 now), so a direct comparison isn't possible.

### Rupa's own parser

Every case whose `command` reaches Rupa with a claim about its parser was also run against Rupa `v0.1.4` itself (`uvx --from git+https://github.com/VajraSarpa/rupa@v0.1.4 rupa …`, `RUPA_LOG=off`) in a fresh folder with an existing `notes.txt`: 36 commands. Each exit code and file change matched the case. Examples:

| Case | Rupa result |
|---|---|
| `rupa in.md --to html -onotes.txt --force` | exit 0, `notes.txt` replaced |
| `rupa -o notes.txt --force --to html verify` | exit 0, renders the file `verify`, `notes.txt` replaced |
| `rupa VERIFY --force --to html -o notes.txt` | exit 0, renders the file `VERIFY`, `notes.txt` replaced |
| `rupa verify out/report.pdf --force` | exit 2, "unrecognized arguments: --force", nothing written |
| `rupa --forc --to html -o notes.txt in.md` | exit 2, "unrecognized arguments: --forc" |
| `rupa in.md -o --force` | exit 2, "-o/--output: expected one argument" |
| `rupa verify out/report.pdf --wants --out` | exit 2, "--wants: expected one argument" |
| `rupa --force --to html -o notes.txt in.md --help` | exit 0, help, nothing written |
| `rupa verify out/report.pdf --out review --help` | exit 0, help, nothing written |

Two behaviours the descriptions rely on, also checked: a plain `rupa b.md -o x.pdf` over an existing `x.pdf` exits 0 and replaces it; and a second `rupa verify y.pdf --out rev` deleted the two sheets the first run's `verify.json` listed, left an unrelated `keep.png` alone, and replaced `verify.json`.

## Fixture cases (83)

57 for `command.rupa.force`, 26 for `command.rupa.verify-out`. Expected actions: 74 review, 5 block, 3 allow, 1 require-reapproval.

- Each flag leading, trailing, and after other options; `--output=x`, `-ox`, `--to=html`, `--out=DIR`; quoted paths with spaces; stdin input.
- `rupa.cmd`, `rupa.exe`, `"/opt/My Tools/rupa"`.
- `&&`, `;` and pipe chains, with the rupa segment first or second.
- Wrappers: `env X=1`, a bare `X=1` assignment, `command`, `exec`, `time`, `timeout 60`, `bash -c '…'` (all unwrapped), `sudo` (unwrapped, `require-reapproval`), `nohup` (not unwrapped; review with no rule evidence).
- Launchers: `uv run`, `uv run --no-sync`, `uv run --`, `uvx --from git+…@v0.1.4`, `uvx rupa@0.1.4`, `uv tool run`.
- `rupa ./verify -o out.pdf` (render; neither rule), `rupa -o out.pdf verify` (render of a file named `verify`), `rupa ./verify --force …` and `rupa -o notes.txt --force --to html verify` (force rule).
- Safe counterparts: `--help`, `-h`, `--version`, `--help` after `--force`, a plain render, `rupa verify PDF`, `rupa verify --json PDF`, `rupa verify --help`/`-h`, `--help` after `--out`.
- A flag swallowed as a value (`-o --force`, `--wants --out`), and `--forc`: no match, and Rupa rejects each.
- Over-matches kept on purpose, each exit 2 in Rupa: `rupa verify PDF --force`, `rupa --force in.md` (no `-o`), `rupa --to html --force -o` (no value), `rupa VERIFY PDF --out review`.
- Malformed input: `rupa $ARGS` (review), `rupa --force $ARGS` (review, force rule), an unbalanced quote, `xargs rupa …` and `$(…)` in an argument (all block).
- Controls: `echo rupa …` and `ls -la` (allow), `other-rupa …` (review, no rule), extension inactive (review, no segments), each permission disabled (block).

## Differences from the dry run and the merged PRs

1. **The descriptor question has moved, and the current repo still disagrees with itself.** The dry run recommended committing `contributions/extensions/command.rupa.json`. At `101bc5f`:
   - `extensions/contributing.md` says to include it in the PR, and that CI fails a PR whose record is missing or stale.
   - `CONTRIBUTING.md`, the implementation map in `extensions/contributing.md`, and `extension-contributions.md` call it maintainer-generated and say to keep generated changes out of contribution PRs.
   - The PR template's checklist names the projections to leave out (catalog, native program, baselines, digest vectors, directory render). It doesn't name descriptors.
   - On #6259, kantorcodes wrote that the contributor owns source, fixture and trust binding, and the descriptor is maintainer-generated; the PR says its generated record wasn't included. Yet both merge commits (`ce949cd`, `cff79d5`) contain the descriptor, and #5911's first CI run failed only because its committed descriptor wasn't canonical.
   - `scripts/ci/verify_native_command_program.py` checks descriptor bytes in git `HEAD` before anything else ("Check Git blobs first; scratch regeneration cannot repair missing PR inputs").
   - **Recommendation:** commit it. It is byte-for-byte what `prepare` writes, so it is not hand-edited, and the CI check reads it from the commit.
2. **A normal PR, not a draft.** CONTRIBUTING and `extensions/contributing.md` still say to open a draft first for a new extension or material authority change. You decided on a normal PR. #5911 was a draft only until CI could run the handoff its author couldn't; this build runs the handoff locally.
3. **Two rules, not three.** The dry run's `command.rupa.render` rule is dropped, as you decided, following rwxmap's precedent. The plain-render overwrite is a stated known limit instead.
4. **Risk class `local_write`, not `destructive_shell`.** The dry run picked `destructive_shell`; rwxmap, the closest merged precedent, uses `local_write`. `local_write` is the narrower and more accurate class: both rules replace or delete local files and nothing else. Risk tier matches severity, as in rwxmap (and 624 of 625 existing rules).
5. **Wrappers.** The dry run listed `nohup` as unwrapped. At `101bc5f` it isn't: `nohup rupa --force …` gives review with no rule evidence. Unbalanced quotes, `xargs` and `$(…)` give `block`, stricter than the review the dry run expected for malformed input.
6. **`uv run`, `uvx`, `uv tool run` are supported** by the existing matchers, as rwxmap does for npx/bunx: `executable.v1` for `uv run` (the `command.pyrig` pattern) and `versioned-package-subcommand.v1` for `uvx` and `uv tool run`. `uv`/`uvx` stay out of `executables`.
7. **The Builder wasn't used.** I hand-wrote the source, as #6259 did, and used `prepare`.
8. **Disk.** The session's disk allowance couldn't hold the full debug test build (14 GB `target/debug` plus 1.5 GB release). The test gate ran with `CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0`. The dry run and nonroot run didn't hit this.
9. **Their aggregate trust map gets rewritten.** `prepare`/`handoff` rewrote the ignored `contracts/extensions/build-trust-class-map.v1.json` with an empty external list. I re-ran `--trust-only` before building the fixture, so the fixture embeds the full map (182 external IDs including `command.rupa`). Nothing for us to fix; noted in case a maintainer sees a different embedded map.
10. **Case-insensitive arguments rule out a `verify` safe variant.** I tried one for the force rule, to stop `rupa verify … --force` matching. Guard lowercases arguments, so the variant also cleared `rupa VERIFY --force -o notes.txt`, a real overwrite. I removed it; the over-match is documented and pinned by a case.

## Open questions

1. **Descriptor in or out** (item 1). My recommendation is in.
2. **Publisher.** I followed rwxmap: `Community`, id `community.rupa`, URL `https://github.com/VajraSarpa`. ccx used the author's own name and an `io.github.<user>` id. Use "Vajra Sarpa" if you want the credit on the record; publisher fields never affect trust.
3. **Allow edits from maintainers.** Left unticked in the PR body: only you can enable it on your fork. Enable it if you want Gitar to commit mechanical repairs.
4. **Launcher option coverage.** `uvx` and `uv tool run` stop at launcher options outside the listed set (for example `--refresh-package`), the same kind of gap Qodo flagged on #6259. Extend the lists now, or wait for review.
5. **The five cargo test failures.** They don't involve `command.rupa`, but a reviewer may ask. The PR body says so and lists them. CI on the PR is the real answer.
6. **`rupa` isn't on PyPI.** `uvx rupa` only works with `--from git+…`. Is that worth a line in the README?

## Local rerun and submission (2026-11-03, Vajra's machine)

Vajra chose a personal publisher (open question 2): `Vajra Sarpa`, id `io.github.vajrasarpa`, after ccx. The source and fixture were edited by hand (two lines each), and the descriptor was regenerated by `prepare_extension_contribution.py`. Everything was then rerun in his fork's clone (`~/Projects/hol-guard`, branch `command-rupa`) on hol-guard `main` at `31e2563`, as uid 1000 on Fedora 43, with Rust 1.88.0 from rustup, bubblewrap 0.12.0 and `umask 022`.

| Check | Result |
|---|---|
| release build of `guard-command-source`, `hol-guard-runtime` | ok, 12m23s |
| `prepare --check`, `--check-trust`, `extensions handoff` | all pass (handoff 3m05s) |
| `verify_native_command_program.py`, on commit `636e86f` | pass, `stale_public_descriptors: []` |
| `cargo fmt --check`, `cargo clippy -D warnings` | pass, 0 warnings (clippy 4m59s) |
| `cargo test --workspace --all-targets --no-fail-fast` | 14,044 passed, 3 failed, 39 ignored, 90 binaries (23m42s). All three fail the same on `main` without the rupa files: a cross-device rename into tmpfs `/tmp`, an open-file cap that didn't hold, and `git add` refusing a path his global `.gitignore` ignores. |

Opened as a normal PR (not a draft), maintainer edits on: [hashgraph-online/hol-guard#7119](https://github.com/hashgraph-online/hol-guard/pull/7119).
