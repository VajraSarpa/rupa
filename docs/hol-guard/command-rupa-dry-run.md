# HOL Guard `command.rupa`: dry run (2026-10-25)

A Claude Code cloud session cloned `hashgraph-online/hol-guard` (`6bf9f88`, main as of 2026-10-25) into its own VM, built it, ran the contributor gates, and drafted the scope answers for a `command.rupa` Command extension from [`docs/cli-contract.md`](../cli-contract.md). Nothing was pushed, forked or opened upstream. This is the session's final report, unedited apart from this header; the log paths it cites were inside that VM and no longer exist.

I ran the dry run end to end. Two of the three cargo gates passed. `cargo test` failed: 45 of 9,093 tests, all apparently because this container runs as root. The draft is ready apart from two blockers, both listed at the end of the differences section. Nothing was committed or pushed anywhere, and Rupa's working tree is clean.

## Setup log (hol-guard `6bf9f88`, main as of 2026-10-25)

| Step | Result | Time |
|---|---|---|
| `git clone` | ok | 41s |
| `uv sync --extra dev --frozen --python 3.12` | ok | 10s |
| `rustup toolchain install 1.88.0 --profile minimal --component rustfmt --component clippy` | ok | 22s |
| `cargo +1.88.0 build --locked --manifest-path rust/Cargo.toml --release -p guard-command -p hol-guard-runtime --bin guard-command-source --bin hol-guard-runtime` | ok | 13m50s |
| `verify_native_command_program.py --compiler rust/target/release/guard-command-source` | ok, 149 projections, program `09bccb63…` | 31s |

The CONTRIBUTING sequence took about 34 minutes of wall time, nearly all of it Rust compilation.

**Problems hit:**
1. **45 test failures, apparently from running as root (uid 0).**
   - Fixtures that `chmod` a config file to make it unreadable are still readable by root (`settings_unreadable`, `config_unreadable` in the adapter and Codex vectors).
   - Ownership checks ("another account can write", `/usr/lib` as a proven loader entry, `bf_private_dir ["/"]`) flip because `/` and `/usr/lib` belong to the running user.
   - The git worktree, commit-signing and shim/`.bashrc` cases follow the same pattern.
   - I didn't re-run as a non-root user, so this cause is inferred, not confirmed.
2. **`cargo test` stops at the first failing crate.** Their command has no `--no-fail-fast`, so the first run only showed 11 failures. A second run with that flag gave the full picture.
3. **The Extension Builder doesn't work in a source checkout.** `hol-guard extensions generate` fails with "authoring requires the verified installed command pack bundle". That happens with Rupa's help text and with their own `samplectl` example, even with all four documented `HOL_GUARD_NATIVE_*` overrides set. The cause is in `bundle_baseline.py`: it only allows an installed bundle or the `development=` hook, and only `prepare_extension_contribution.py` passes that hook.
4. `uv` prints an `UV_NATIVE_TLS` deprecation warning from this environment. It's harmless.

## Gate results

| Gate (their exact form, `--manifest-path rust/Cargo.toml`) | Result |
|---|---|
| `cargo +1.88.0 fmt --all --check` | **pass** (17s) |
| `cargo +1.88.0 clippy --locked --workspace --all-targets -- -D warnings` | **pass**, 0 warnings (5m28s) |
| `cargo +1.88.0 test --locked --workspace --all-targets` | **fail**: 9,041 passed, 45 failed, 7 ignored, across 74 test binaries (12m51s first run, 16m49s with `--no-fail-fast`) |

The failing targets are `guard-command` lib (11), `--test integration` (18), `pretool_git_publish_chain` (1), `shim_admin_vectors` (1) and `hol-guard-runtime` lib (14). None of them touch command-source compilation. The full logs were in the session's scratchpad (`setup.log`, `test-nff.log`).

## Seven-point scope answers for `command.rupa`

**1. Boundary and ID: `command.rupa`.**
- **In scope:** Rupa commands that create, replace or delete local files:
  - a render replacing `OUT`;
  - `--force` replacing a file that isn't `.html` or `.pdf`;
  - `verify --out DIR` replacing and deleting sheets in a folder the caller picks.
- **Out of scope:** network and subprocess risk (Rupa does neither), and `rupa refs`, which is a maintainer command.
- **ID:** a single tool, so no domain segment, following the `command.codesage` pattern.

**2. Executables and subcommands.**
- **Executables:** `rupa`, `rupa.exe`, `rupa.cmd`. Guard matches by basename, so `"/opt/My Tools/rupa"` is covered.
- **Subcommands covered:** the bare render (`rupa [INPUT] -o OUT`) and `verify`. `refs` isn't covered and falls back to Guard's default review for any command it doesn't recognise.
- **Wrappers:** `uv run rupa` and `uvx rupa` need explicit matchers, as `command.pyrig` does for `uv run`. Guard doesn't unwrap package runners, and `uv`/`uvx` are owned by `command.package.python`, so they go in matchers only, never in `executables`.
- **`python -m rupa` doesn't exist** (there's no `__main__.py`), so it isn't covered.
- **Version:** Rupa v0.1.3 behaviour, from `docs/cli-contract.md`.
- **Dialects:** POSIX shell and Windows `.exe`/`.cmd`.

**3. A risky and a safe command per family** (each rule is one permission):

| Rule | Severity | Risky example | Safe counterpart |
|---|---|---|---|
| `command.rupa.force-overwrite` | high | `rupa --to html --force -o notes.txt in.md` | `rupa --to html -o out/new.html in.md`; `--help` |
| `command.rupa.verify-out` | medium | `rupa verify out/r.pdf --out ~/shared` | `rupa verify out/r.pdf` (default `<pdf>.verify/` falls outside the rule) |
| `command.rupa.render` | low | `rupa notes.md -o report.pdf` (silently replaces `report.pdf`) | `rupa --help`, `rupa -h`, `rupa --version` |

**4. Fixture cases for compound commands, wrappers, quoting, reordered flags and malformed input.** Expected results follow the conventions in existing fixtures.

- **Compound:**
  - `rupa a.md -o a.pdf && rupa verify a.pdf` → render rule on segment 0.
  - `cat a.md | rupa -o a.pdf` → segment 1.
  - `rupa --help; rupa --force --to html -o x.txt` → segment 1.
- **Wrappers:**
  - `exec`, `env X=1`, `command`, `nohup`, `time`, `timeout`, `sudo`, `bash -c '…'` are unwrapped by Guard (`sudo` gives `require-reapproval`).
  - `xargs rupa …` and `exec -a x rupa …` give `block` with no segments.
  - `uv run --no-sync rupa …` and `uvx rupa …` need the explicit matchers above.
- **Quoting:** `rupa "my notes.md" -o "out/my report.pdf"` and `--output='a b.pdf'`.
- **Reordered flags:** `rupa -o x.txt --force in.md --to html` and `rupa --json --pages 2 -o x.pdf in.md`.
- **Equals and attached forms:** `--output=x.pdf` and `-ox.pdf`.
- **Case:** Guard lowercases arguments, so `RUPA.CMD` and `rupa VERIFY` over-match. That's acceptable because it errs towards review.
- **Name collision:** `rupa ./verify -o out.pdf` must hit render, not verify.
- **Malformed input, each keeping review:** `rupa -o` with no value, `rupa $ARGS`, an unbalanced quote, `rupa --force` with no `-o`.
- **Controls:** the extension disabled gives review with no segments; a disabled permission gives `block`; `other-rupa -o x` doesn't match.
- **Blocker:** argparse's `allow_abbrev` is on in `cli.py`, so `--forc`, `--fo` and `--f` all mean `--force`, and `--outp` means `--output`. A literal matcher misses these.
  - **Recommended:** Rupa v0.1.4 sets `allow_abbrev=False` before the PR. That's a contract change and goes in the release notes.
  - **Fallback:** enumerate every prefix in the matchers.

**5. Risk and action classes, floors, severity, safer alternatives.**
- **Risk class:** `destructive_shell` on all three rules, as dearmour, vttforge and hashdup do for overwrites. It maps to `DestructiveOrIrreversibleOperation`.
  - It's also on Guard's fail-closed list when its authority is unavailable. Ask in the draft PR whether that's too strong for a plain render.
  - The `filesystem_write` that iterlay uses isn't in the native vocabulary, so I avoided it.
- **Floors:** all three permissions use `baseline_floor: review`, `default_enabled: true`, `configurable: true`, with risk tier matching severity.
- **Action classes:** "Rupa output replacement", "Rupa forced overwrite of a non-HTML/PDF file", "Rupa verify sheet write and delete".
- **Safer alternatives:**
  - render: "write to a new path; rupa replaces an existing .html/.pdf without asking";
  - force: "drop --force and write a new .html/.pdf";
  - verify-out: "omit --out (sheets go to `<pdf>.verify/`) or point --out at an empty folder".

**6. Overlap.**
- No existing extension covers `rupa`; I grepped the sources and contracts for it.
- `package.python` owns `uv`/`uvx` and delegates to the package firewall. Our `uv run`/`uvx` matchers add on top, and the stricter result wins.
- `shell-mutations` sees `>` redirection but not `--force -o ~/.bashrc`. That gap is the case for a separate identity.

**7. Privacy and performance.**
- **Privacy:** Rupa makes no network calls and runs no subprocesses. The extension does bounded argv matching only, and receipts keep redacted digests, never paths or document text.
- **Performance:** roughly 5–8 `executable.v1` nodes under `any.v1`. That's far below the 16,384-node and 1,024-rule limits, and the compiler derives executable candidate hints, so other commands skip these rules.
- **References:** `docs/cli-contract.md`, README#contract, `src/rupa/cli.py`.

## Differences from your plan

1. **The fourth file is `contributions/extensions/command.rupa.json`**, the v2 descriptor written by `prepare_extension_contribution.py` via `--publish-descriptor`. Their docs disagree on whether to commit it:
   - `extensions/contributing.md` says to include it, and that CI fails a PR with a missing or stale record.
   - `extension-contributions.md` lists it among projections contributors don't include.
   - CONTRIBUTING says descriptors are maintainer-published.
   - **Recommendation:** include it, since the script and CI require it, and say so in the draft PR.
2. **The Builder is optional and doesn't work from a checkout** (problem 3 above). You can either hand-write the source and run `prepare` (a documented route), or install the `hol-guard` wheel to use `extensions generate`. For an argparse CLI the input would be `--from help`, which is partial, or a hand-written `guard.cli-surface.v1` JSON.
3. **The trust binding is generated, not hand-written.** `python scripts/refresh_extension_artifacts.py --trust-only` creates it as `external`.
4. **The fixture embeds the full source.** It must carry an exact copy in `build.sources`, so every source edit means re-embedding it.
5. **The seven-point bar isn't in the PR template.** It's in `extensions/contributing.md` under "Scope review quality bar". The template's sections are What changed / Upstream source and version / Capability boundary / Fast validation / Checklist, so the answers need mapping into those.
6. **Open a draft PR from a fork first**, so maintainers can review the ID before implementation. Doing that is your call, not part of this dry run.
7. **Safe commands never become `allow`.** An external extension stays off until a local admin enables it. Even when enabled, safe variants only clear that rule's segments; Guard still asks for review on every rupa command, because review is the default for tools it doesn't recognise. So `command.rupa` won't reduce Claude's prompts. It adds classification, approval-card evidence and a block switch. Users keep "Always allow" under Guard's approval rules.
8. **Version pin.** `docs/cli-contract.md` isn't in the `v0.1.3` tag (it landed in `4a3cb86`), although `src/` is identical between v0.1.3 and HEAD. Pin `4a3cb86`, or tag v0.1.4 together with the `allow_abbrev` fix.
9. **Extras in their docs that your plan didn't cover:**
   - an optional `contributions/extension-listings/command.rupa.json` for publisher credit;
   - `prepare --check` and `hol-guard extensions handoff` as the validation to paste into the PR;
   - optional Guard Gauntlet live evidence.

**Blockers before a real PR:** decide on `allow_abbrev` in Rupa, and confirm the 45 test failures are root-only by re-running as a normal user.
