#!/usr/bin/env bash
# Compare Claude Code on the same task across arms (bench v2; see bench/PLAN.md):
#   baseline         no plugin: Claude writes the HTML/CSS and finds its own PDF tool
#   baseline-hinted  no plugin, plus a three-line CLAUDE.md on how to make a PDF
#   rupa-verify      plugin as shipped: render, then verify; sheets only for flagged pages
#   rupa             plugin, render only (the skill's Verify section is removed)
#   rupa-pertype     plugin, verify with a sheet per page type as well as flagged pages
#
# Usage: TASK=report bench/bench.sh [runs]       default 1 run per arm (a pilot)
#   TASK      a folder under bench/tasks/ (prompt.txt, output, checks.json, optional
#             inputs/). A session task has several prompts in prompt.txt, separated
#             by lines of ---, and one output per line in output; each prompt after
#             the first resumes the same Claude Code session.
#   MODEL     default claude-opus-5-5
#   ARMS      default "baseline baseline-hinted rupa-verify"
#   SEED      seeds the arm order of each run (default: the date)
#   TIMEOUT   seconds per run (default 1500); a timeout is a failed run
#   RESULTS_ROOT  default bench/results
#   FREEZE_TAG    Rupa's src/, plugin/ and lockfile must match it (default v0.1.2);
#                 FREEZE_TAG=off skips the check (tests only)
#
# Each run starts in a fresh empty directory, so no arm can see this repo, and
# runs with user plugins, skills and MCP servers off, so only the arm's plugin
# (if any) loads. Arms are interleaved: each run number goes through every arm
# in a shuffled order.
set -euo pipefail

RUNS="${1:-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_NAME="${TASK:-report}"
TASK_DIR="$ROOT/bench/tasks/$TASK_NAME"
[[ -f "$TASK_DIR/prompt.txt" ]] || { echo "bench: no task $TASK_DIR/prompt.txt" >&2; exit 2; }
OUTPUTS=()
[[ -f "$TASK_DIR/output" ]] && mapfile -t OUTPUTS < <(grep -v '^[[:space:]]*$' "$TASK_DIR/output")
[[ ${#OUTPUTS[@]} -gt 0 ]] || OUTPUTS=(report.pdf)
OUTPUT="${OUTPUTS[0]}"
MODEL="${MODEL:-claude-opus-5-5}"
ARMS="${ARMS:-baseline baseline-hinted rupa-verify}"
SEED="${SEED:-$(date +%Y%m%d)}"
TIMEOUT="${TIMEOUT:-1500}"
FREEZE_TAG="${FREEZE_TAG:-v0.1.2}"
TOOLS="Bash Write Read Edit Skill"
ISOLATE=(--setting-sources project --strict-mcp-config)

for arm in $ARMS; do
  case "$arm" in baseline|baseline-hinted|rupa|rupa-pertype|rupa-verify) ;;
    *) echo "bench: unknown arm $arm" >&2; exit 2 ;; esac
done
command -v rupa >/dev/null || { echo "bench: rupa is not on PATH" >&2; exit 2; }

# Freeze: the Rupa under test is the tagged one, both the CLI and the plugin.
if [[ "$FREEZE_TAG" != off ]]; then
  if ! git -C "$ROOT" diff --quiet "$FREEZE_TAG" -- src plugin pyproject.toml uv.lock; then
    echo "bench: src/, plugin/ or the lockfile differ from $FREEZE_TAG; tag a release first" >&2
    exit 2
  fi
  want="rupa $(git -C "$ROOT" show "$FREEZE_TAG:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p')"
  have="$(rupa --version)"
  [[ "$have" == "$want" ]] || {
    echo "bench: installed $have, but $FREEZE_TAG is $want; run uv tool install --reinstall ." >&2
    exit 2
  }
fi

RESULTS="${RESULTS_ROOT:-$ROOT/bench/results}/$(date +%Y%m%d-%H%M%S)-$TASK_NAME"
mkdir -p "$RESULTS"
cp -r "$TASK_DIR" "$RESULTS/task"
STEPS="$(python3 "$ROOT/bench/result.py" --split "$TASK_DIR/prompt.txt" "$RESULTS/steps")"
[[ "$STEPS" -eq ${#OUTPUTS[@]} ]] || {
  echo "bench: $STEPS prompts but ${#OUTPUTS[@]} outputs in $TASK_DIR" >&2; exit 2; }
export RUPA_LOG=off  # keep benchmark runs out of the real-use failure log

# The plugin as tagged (or as in the tree, with the freeze off), without evals/.
FROZEN="$RESULTS/plugin"
if [[ "$FREEZE_TAG" != off ]]; then
  git -C "$ROOT" archive "$FREEZE_TAG" plugin | tar -x -C "$RESULTS"
else
  cp -r "$ROOT/plugin" "$FROZEN"
fi
rm -rf "$FROZEN/evals"
SKILL="$FROZEN/skills/render/SKILL.md"

# Render only: the skill stops before "## Verify".
NOVERIFY="$RESULTS/plugin-noverify"
cp -r "$FROZEN" "$NOVERIFY"
awk '/^## Verify/ {skip=1} /^Do not add styling/ {skip=0} !skip' \
  "$SKILL" > "$NOVERIFY/skills/render/SKILL.md"

# Per-type: verify also makes one sheet per page type, even on a clean PDF.
PERTYPE="$RESULTS/plugin-pertype"
cp -r "$FROZEN" "$PERTYPE"
sed 's/`rupa verify out\/report.pdf`/`rupa verify --sample per-type out\/report.pdf`/' \
  "$SKILL" > "$PERTYPE/skills/render/SKILL.md"
grep -q -- '--sample per-type' "$PERTYPE/skills/render/SKILL.md" \
  || { echo "bench: could not make the per-type skill; SKILL.md changed?" >&2; exit 2; }

# What the hinted baseline is told. Written before any v2 run; see bench/PLAN.md.
HINT='To make a PDF, write one HTML file with a print stylesheet (@page size and margins, body text 10-11pt).
Print it with: google-chrome --headless=new --no-pdf-header-footer --print-to-pdf=OUT.pdf FILE.html
Check the page count with pdfinfo OUT.pdf and adjust the HTML until it matches what was asked.'

python3 - "$RESULTS/manifest.json" <<EOF
import json, subprocess, sys, hashlib
def out(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""
json.dump({
    "bench": 2, "task": "$TASK_NAME", "output": "$OUTPUT", "outputs": "${OUTPUTS[*]}".split(),
    "steps": $STEPS, "model": "$MODEL",
    "arms": "$ARMS".split(), "runs": $RUNS, "seed": "$SEED", "timeout": $TIMEOUT,
    "freeze_tag": "$FREEZE_TAG", "rupa_version": out("rupa", "--version"),
    "claude_version": out("claude", "--version"),
    "bench_commit": out("git", "-C", "$ROOT", "rev-parse", "HEAD"),
    "bench_dirty": bool(out("git", "-C", "$ROOT", "status", "--porcelain", "bench")),
    "prompt_sha256": hashlib.sha256(open("$TASK_DIR/prompt.txt", "rb").read()).hexdigest(),
    "tools": "$TOOLS", "isolation": "${ISOLATE[*]}",
    "started": out("date", "-Iseconds"),
    # What a baseline run could reach for to make a PDF.
    "host_tools": {t: out("sh", "-c", f"command -v {t}") for t in
                   ("google-chrome", "chromium", "pandoc", "weasyprint", "wkhtmltopdf",
                    "pdfinfo", "pdftotext", "python3", "rupa")},
    "python3": out("python3", "--version"),
    "python3_modules": {m: not subprocess.run(["python3", "-c", f"import {m}"],
                                              capture_output=True).returncode
                        for m in ("reportlab", "weasyprint", "fpdf", "markdown", "docx")},
}, open(sys.argv[1], "w"), indent=2)
EOF

run_one() {  # $1 = arm, $2 = run number, $3 = position in this run's order
  local arm="$1" i="$2" pos="$3" work flags=() start rc=0
  work="$(mktemp -d)"
  [[ -d "$TASK_DIR/inputs" ]] && cp -r "$TASK_DIR/inputs/." "$work/"
  case "$arm" in
    baseline-hinted) printf '%s\n' "$HINT" > "$work/CLAUDE.md" ;;
    rupa) flags=(--plugin-dir "$NOVERIFY") ;;
    rupa-pertype) flags=(--plugin-dir "$PERTYPE") ;;
    rupa-verify) flags=(--plugin-dir "$FROZEN") ;;
  esac
  echo "bench: $TASK_NAME $arm run $i" >&2
  start="$(date +%s)"
  local k sid="" resume=() out
  : > "$RESULTS/$arm-$i.jsonl"
  for k in $(seq 1 "$STEPS"); do
    resume=()
    [[ -n "$sid" ]] && resume=(--resume "$sid")
    ( cd "$work" && timeout "$TIMEOUT" claude -p "$(cat "$RESULTS/steps/$k.txt")" \
        --output-format stream-json --verbose --model "$MODEL" --allowedTools "$TOOLS" \
        "${ISOLATE[@]}" ${flags[@]+"${flags[@]}"} ${resume[@]+"${resume[@]}"} ) \
      >> "$RESULTS/$arm-$i.jsonl" 2>> "$RESULTS/$arm-$i.err" || rc=$?
    # Keep each step's output now: a later step may overwrite the same file.
    out="${OUTPUTS[$((k - 1))]}"
    if [[ -s "$work/$out" ]]; then
      if [[ "$STEPS" -eq 1 ]]; then
        cp "$work/$out" "$RESULTS/$arm-$i.${out##*.}"
      else
        cp "$work/$out" "$RESULTS/$arm-$i.s$k.${out##*.}"
      fi
    fi
    [[ "$rc" -eq 0 ]] || break
    sid="$(python3 "$ROOT/bench/result.py" --session "$RESULTS/$arm-$i.jsonl")"
    [[ -n "$sid" ]] || { rc=1; break; }
  done
  # One step: the result event as --output-format json prints it. Several: summed.
  python3 "$ROOT/bench/result.py" "$RESULTS/$arm-$i.jsonl" "$STEPS" "$rc" > "$RESULTS/$arm-$i.json"
  cp -r "$work" "$RESULTS/$arm-$i.work"
  rm -rf "$work"
  printf '{"arm": "%s", "run": %d, "position": %d, "start": %d, "secs": %d, "exit": %d}\n' \
    "$arm" "$i" "$pos" "$start" "$(( $(date +%s) - start ))" "$rc" >> "$RESULTS/manifest.jsonl"
}

for i in $(seq 1 "$RUNS"); do
  pos=0
  order="$(python3 -c 'import random, sys; a = sys.argv[2:]; random.Random(sys.argv[1]).shuffle(a); print(*a)' "$SEED-$i" $ARMS)"
  for arm in $order; do
    pos=$((pos + 1))
    run_one "$arm" "$i" "$pos"
  done
done

echo "bench: results in $RESULTS" >&2
python3 "$ROOT/bench/summarize.py" "$RESULTS"
