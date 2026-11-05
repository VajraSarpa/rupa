# `command.rupa` on HOL Guard 3.59.0: after-release test

Run 2026-11-05 on Fedora 43 (x86_64), following the after-release steps in
HOL Guard's `docs/guard/extensions/contributing.md` (lines 97–116). The
extension was merged in
[hashgraph-online/hol-guard#7119](https://github.com/hashgraph-online/hol-guard/pull/7119)
and first released in v3.59.0.

**Outcome:** no file was harmed. Both destructive cases were held and denied.
But Guard never named `command.rupa`. Every rupa command Guard tried to
inspect for the extension came back `native_unavailable`, and the agent saw
the same generic "not proven read-only" review for safe and destructive rupa
commands alike. That differs from the fixture.

## Setup

| Item | Value |
|---|---|
| HOL Guard | `hol-guard 3.59.0`, installed with `pipx install hol-guard` (install mode `official-pipx`) |
| Native runtime build | `3.59.0+fc5f50cca519ccacfeae8edea4f0c4744d788d67` |
| Rupa | 0.1.5 (`uv tool install git+https://github.com/VajraSarpa/rupa@v0.1.5`) |
| Harness | Claude Code, hooks installed by `hol-guard install claude-code --workspace ~/guard-test` |
| Test folder | `~/guard-test`, outside any repo: `in.md`, and `notes.txt` seeded with "These notes must survive." |
| Guard posture | `doctor`: Protection `Protected`, local trust mode `degraded_safe`, remembered rules `disabled_degraded` |

Steps, in order:

```sh
hol-guard command test 'echo guard-install-check' --json        # no_match, native parse "exact"
hol-guard install claude-code --workspace ~/guard-test
hol-guard doctor claude-code
# dashboard: Settings > Approval gate, set a password (see Finding 2)
hol-guard command controls apply command.rupa --target-kind extension --state enabled
# -> {"status":"applied","revision":2,...}
hol-guard command controls status                                # health "protected", command.rupa local_state "enabled"
hol-guard command explain 'rupa in.md --to html --force -o notes.txt'
```

## Results

### Inspection (`hol-guard command test --json`, extension enabled)

| Command | Fixture expects | Guard 3.59.0 |
|---|---|---|
| `rupa in.md -o out.html` | no match | `no_match`, native parse `exact` |
| `rupa in.md --to html --force -o notes.txt` | `review`, rule `command.rupa.force` | `native_unavailable`, `command_model: null`, no rule |
| `rupa verify out.pdf --out review` | `review`, the `verify --out` rule | `native_unavailable`, `command_model: null`, no rule |
| `git push --force origin main` (built-in, for comparison) | — | `review`, rule `command.git.force-push` |
| `echo guard-install-check` (control) | — | `no_match`, native parse `exact` |

`command explain` on the `--force` case gives the same result:
"Native inspection is unavailable. Check native runtime and command-control
status." Command control was healthy at the time (`health: protected`).

Before the extension was enabled, the same `--force` command returned
`no_match`, with a native command model. Inspection fails only for commands
`command.rupa` would match, and only once it is on.

`minimum_action` stayed `review` in every `native_unavailable` case, so Guard
fails closed.

### Agent run (Claude Code, hooks active)

| Command | Fixture expects | What happened |
|---|---|---|
| `rupa in.md -o out.html` | runs | held for review; ran after a one-time allow |
| `rupa in.md --to html --force -o notes.txt` | review, deny | held; denied; `notes.txt` unchanged |
| `rupa in.md -o out.pdf` (setup for the next case) | runs | held for review; ran after a one-time allow |
| `rupa verify out.pdf --out review` | review, deny | held; denied; no `review/` folder created |

All four holds gave the agent the same reason: "Step 2 (rupa) is not proven
read-only" (`rupa verify` for the last). None mentioned `--force`, the
target file, `command.rupa`, or the extension's safer alternatives.

`hol-guard receipts` recorded four local decisions (allow, block, allow,
block), each as a generic Bash "approval decision", with no extension or
rule named.

## Findings

1. **`command.rupa` is not evaluated natively in 3.59.0.** Any command the
   extension matches returns `native_unavailable`. The installed Python
   package carries the extension, in
   `guard/contracts/data/extensions/command-pack-bundle/assets/000000/objects-000130.zip`
   and `assets/000001/objects-00000{0,1}.zip`. The native runtime binary
   (`codex_plugin_scanner/_native/hol-guard-runtime`) contains the built-in
   rule ID `command.git.force-push` as plain text, but no `command.rupa.*` ID.
   A likely explanation is that the 3.59.0 native runtime was built from a
   catalog that predates the extension. That is unconfirmed: the runtime
   may load rules from the bundle, and Guard's diagnostics under
   `~/.hol-guard` were not read during this test.
2. **Enabling an extension needs an approval gate first.** On a fresh
   install, `controls apply` printed only
   `Error: Guard daemon request failed: approval_required`, without
   prompting. The daemon's underlying error is
   `approval_gate_configuration_required` ("Configure the approval gate
   before changing extension controls"; `guard/approval_gate.py`).
   After setting a password in the dashboard (Settings > Approval gate),
   `apply` prompted for it and succeeded. Neither contributing.md's
   after-release steps nor the extension's getting-started text mention this.
3. **`install claude-code --workspace DIR` writes global hooks.** The hooks
   went to `~/.claude/settings.json`, and `doctor` lists each one as scope
   `global`. `--workspace` is only passed into the hook commands.
   `get-started.md` ("What `install` does") says Claude Code "gets Guard hook
   entries in `.claude/settings.local.json` when you install from a
   workspace". The code always uses `~/.claude/settings.json`
   (`guard/adapters/claude_hook_config.py`, `claude_managed_settings_path`).
   Every Claude Code session on the account was guarded until uninstall.
4. **In `degraded_safe` mode, safe rupa runs also need approval.** This is
   probably Guard's general degraded-mode behaviour rather than anything
   specific to `command.rupa`, but it means the "safe counterpart should
   proceed" case can't pass on a machine in this mode.

5. **`uninstall --self` fails while Claude Code is connected.** It stopped
   with `native_resident_update_in_progress` ("HOL Guard removal stopped at
   harness claude-code before the package uninstall command ran. Nothing had
   been removed yet"). It failed twice, the second time with no other Guard
   window open. In the source, `uninstall --self` holds the exclusive
   native-resident update barrier
   (`guard/cli/uninstall_commands.py`, `hold_native_resident_update_lock`)
   while it disconnects harnesses, and native requests refuse while that
   barrier is held (`guard/cli/update_resident_barrier.py`). Workaround that
   worked:
   ```sh
   hol-guard uninstall claude-code --workspace ~/guard-test   # "Guard hook entries removed"
   hol-guard uninstall --self
   ```
   The second command removed the package, the `~/.hol-guard` state and the
   pipx venv, but ended with
   `No module named 'codex_plugin_scanner.guard.cli.render'`, apparently
   because the package was deleted before the final report printed. It
   also left an empty `"hooks"` object (seven empty event lists) in
   `~/.claude/settings.json`. That object is harmless, and it was removed by
   restoring the pre-install copy.

## Follow-ups

- **Upstream (Vajra's call):** report Finding 1 to HOL Guard, as the
  contributing guide asks ("If the agent experience differs from your
  fixture, open a follow-up pull request with the case that exposed it").
  An issue may suit better than a PR, since the fixture itself still looks
  right. Findings 2 and 3 are docs issues in the same repo.
- **Descriptor wording for Rupa 0.1.5** (separate, from the CLI contract):
  `command.rupa`'s description and safer alternatives say a plain render
  replaces "an existing .html or .pdf". Since v0.1.5 that includes `.docx`.
  `referenceUrls` point at v0.1.4. Fold this into the same follow-up.
- **Extension Studio:** the setup guide should cover the approval gate
  (Finding 2) and say that Guard's hooks are global (Finding 3).
- **Retest** when a Guard release changes the native runtime.

Cleanup afterwards: the two-step uninstall in Finding 5;
`~/.claude/settings.json` restored byte-for-byte to its pre-install copy;
`~/guard-test` deleted. `pipx` itself (`dnf`) was left installed.
