# HOL Guard test gate as a normal user (2026-10-26)

A Claude Code cloud session re-ran hol-guard's `cargo test` gate to check the [dry run](command-rupa-dry-run.md)'s guess that its 45 failures came from running as root. It tested `6bf9f88` (the dry-run commit) and main at `2dc9e9a`, as a normal user and then as root. Nothing was pushed, forked or opened upstream. This is the session's final report, unedited apart from this header; the log paths it cites were inside that VM and no longer exist.

**Short version:** with umask 022, the clone under home rather than `/tmp`, `ssh-keygen` installed and bubblewrap 0.11 or later, the gate passes completely as a normal user (9,243 / 0 / 7). As root in that same setup, 76 tests fail, all for root-specific reasons. None of the failures points to a bug in hol-guard's code.

---

**Verdict: partly root-only.** In a correctly set-up environment, hol-guard's test gate passes completely as a normal user and fails 76 tests as root. The dry run's 45 failures mixed root-only failures with gaps in that container's setup, so the dry-run doc's inference was right only in part.

## Commits tested
- `6bf9f88edec5328884d18b3e9afbe1ef8342aada`: the dry-run commit, tested first.
- `2dc9e9a24fda7e51df923919b63a6b0390d60ec4`: main, 28 commits ahead of it.

Nothing was pushed, forked or opened upstream. Rupa's working tree is clean and nothing was committed.

## Setup
1. **Clone:** cloned hol-guard to `/tmp/hol-guard`, created user `guardtest` (`id -u` = 30033) and gave it ownership of the clone.
2. **Proxy:** copied the proxy settings and CA bundle into guardtest's `~/.profile`.
3. **rustup:** this environment's proxy blocks `sh.rustup.rs`, so I installed rustup by copying root's binary as `rustup-init`. Toolchain 1.88.0 then installed with `--profile minimal --component rustfmt --component clippy`.
4. **uv:** root's binary copied to `/usr/local/bin`. The cargo gate doesn't use it.
5. **Gate command, every run:** `cargo +1.88.0 test --manifest-path rust/Cargo.toml --locked --workspace --all-targets --no-fail-fast`.

## Totals
| Run | Commit | Passed / failed / ignored | Binaries | Time |
|---|---|---|---|---|
| Non-root, login umask 002, clone in `/tmp` | `6bf9f88` | 8,935 / **151** / 7 | 74 | 28m26s |
| Non-root, umask 022, clone in `/tmp` | `6bf9f88` | 9,056 / **30** / 7 | 74 | 19m09s |
| Non-root, umask 022, clone in home (only the 4 failing `guard-command` targets) | `6bf9f88` | **3** failed | — | 13m48s |
| Non-root, umask 022, clone in home | main | 9,240 / **3** / 7 | 76 | 25m59s |
| **Non-root, all fixes below** | main | **9,243 / 0 / 7** | 76 | 18m04s |
| **Root, same fixed environment** | main | **9,167 / 76 / 7** | 76 | 26m34s |

## What I changed (step 5), and the effect on the non-root failures
| Change | Failures it cleared | Why |
|---|---|---|
| `umask 022` (`su -` gives guardtest 002 because `/etc/login.defs` has `USERGROUPS_ENAB yes`) | 121 of 151 | Fixtures come out group-writable, and Guard's trust checks treat group write as "another account can write". |
| Clone under `/home/guardtest` instead of `/tmp` | 25 | Fixtures are created under `rust/target`, and Guard handles locations under world-writable `/tmp` differently from home: home-layout, sibling-glob, worktree-outside-home, socket-directory, launch-root and `.bashrc` shim cases. |
| `apt install openssh-client` | 2: `pretool_git_rebase_signing::{signed_commits_need_the_users_installed_signing_program, commit_signing_by_default_only_holds_writes_that_create_commits}` | The tests say "`ssh-keygen` is installed on every host these tests run on"; this container didn't have it. |
| Built bubblewrap **0.11.0** from source and installed it as `/usr/bin/bwrap` (Ubuntu's 0.9.0 kept at `/usr/bin/bwrap-0.9.0`) | 3: `pretool_extension_allow_merge::a_merge_without_an_allow_still_waits_for_review`, `pretool_find_exec_programs::a_literal_interpreter_name_in_an_exec_body_is_an_argument`, `pretool_git_publish_chain::checks_before_a_proven_publish_run_contained_then_publish` | Guard's Linux sandbox probe needs `bwrap --overlay-src`, which only exists from 0.11. Without it, workspace containment is unavailable. These three also failed identically as root, so they aren't about uid. |
| `git config --global user.name/email` | none | I tried it, it changed nothing, and I removed it. |
| Minimal `PATH` | none | Tried it; changed nothing. |

**Remaining non-root failures: none.** No test looks like a real bug in their code.

## Root-only failures (root, same fixed environment, main)
All 76 are the same set with or without root's global `~/.gitconfig`. That file turns on commit signing in this container, so I moved it aside for one re-run and then restored it.

| Group | Count | Cause |
|---|---|---|
| `workspace_contained*` (python, uv, go, cargo, maven, sibling, vendored, runner, identity) | 42 | Sandboxed runs don't work as uid 0, for example `"native_command_review_required"` where `"native_workspace_containment_required"` is expected. These only show up once bwrap 0.11 makes the sandbox available. |
| Recorded-vector replays (claude_code, codex, copilot, hermes, pi, zcode, aibom, cisco_preflight, openclaw, adapters ×5) | 15 | `chmod`-unreadable fixtures such as `settings_unreadable` are still readable by root. |
| Ownership and trusted-location checks | 19 | Root owns `/`, `/usr/lib` and the socket folders, so "another account can write" and "proven loader entry" checks flip. Examples: `system_directory_stays_a_proven_loader_entry`, `a_socket_directory_*`, `launch_roots ×3`, `chain_literals_pwd ×3`, `pretool_process_probe_chains ×2`, `shims::audit::refuses_an_untrusted_symlinked_ancestor…`. |

That root gets 76 here and 45 in the dry run fits this picture. The dry run had no bwrap 0.11, so most of the 42 sandbox tests couldn't fail there. It also had no `ssh-keygen` and used the `/tmp` location. The dry run didn't record test names, so I can't map its 45 one by one.

## Container changes left behind
- user `guardtest`
- `openssh-client`
- bubblewrap 0.11.0 at `/usr/bin/bwrap`
- meson and build dependencies

All logs and failure lists are in `/tmp/guardlogs/`. I deleted the build folders to free disk space.

**Verdict: partly root-only (76 of 9,243 fail only as root; non-root is 0 failures once umask, clone location, `ssh-keygen` and bubblewrap ≥ 0.11 are set up).**
