#!/usr/bin/env bash
# Compare Claude Code cost on the same task across four arms:
#   baseline       no plugin: Claude writes the HTML/CSS and finds its own PDF tool
#   rupa           plugin, render only (the skill's Verify section is removed)
#   rupa-pertype   plugin, verify with a sheet per page type as well as flagged pages
#   rupa-verify    plugin as shipped: render, then verify; sheets only for flagged pages
#
# Usage: bench/bench.sh [runs]        default 1 run per arm (a pilot)
#        MODEL=claude-sonnet-5-5 bench/bench.sh 3
#        TASK=guide bench/bench.sh 3    prompt from bench/tasks/<TASK>.txt
#                                        (default: report, a 2-page prose report)
# Each run starts in a fresh empty directory, so no arm can see this repo.
set -euo pipefail

RUNS="${1:-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_NAME="${TASK:-report}"
TASK_FILE="$ROOT/bench/tasks/$TASK_NAME.txt"
[[ -f "$TASK_FILE" ]] || { echo "bench: no task $TASK_FILE" >&2; exit 2; }
TASK_PROMPT="$(cat "$TASK_FILE")"
RESULTS="$ROOT/bench/results/$(date +%Y%m%d-%H%M%S)-$TASK_NAME"
TOOLS="Bash Write Read Edit Skill"
MODEL_FLAG=()
[[ -n "${MODEL:-}" ]] && MODEL_FLAG=(--model "$MODEL")

mkdir -p "$RESULTS"
cp "$TASK_FILE" "$RESULTS/task.txt"
command -v rupa >/dev/null || { echo "bench: rupa is not on PATH" >&2; exit 2; }

# Variant arms use a copy of the plugin with an edited skill.
# Copy only what loads, not evals/ and its results.
plugin_copy() {  # $1 = directory to create
  mkdir -p "$1"
  cp -r "$ROOT/plugin/.claude-plugin" "$ROOT/plugin/hooks" "$ROOT/plugin/skills" "$1/"
}
SKILL="$ROOT/plugin/skills/render/SKILL.md"

# Render only: the skill stops before "## Verify".
NOVERIFY="$RESULTS/plugin-noverify"
plugin_copy "$NOVERIFY"
awk '/^## Verify/ {skip=1} /^Do not add styling/ {skip=0} !skip' \
  "$SKILL" > "$NOVERIFY/skills/render/SKILL.md"

# Per-type: verify also makes one sheet per page type, even on a clean PDF.
PERTYPE="$RESULTS/plugin-pertype"
plugin_copy "$PERTYPE"
sed 's/`rupa verify out\/report.pdf`/`rupa verify --sample per-type out\/report.pdf`/' \
  "$SKILL" > "$PERTYPE/skills/render/SKILL.md"
grep -q -- '--sample per-type' "$PERTYPE/skills/render/SKILL.md" \
  || { echo "bench: could not make the per-type skill; SKILL.md changed?" >&2; exit 2; }

run_arm() {  # $1 = arm name, remaining args = extra claude flags
  local arm="$1"; shift
  for i in $(seq 1 "$RUNS"); do
    local work; work="$(mktemp -d)"
    echo "bench: $arm run $i" >&2
    ( cd "$work" && claude -p "$TASK_PROMPT" --output-format json --allowedTools "$TOOLS" \
        ${MODEL_FLAG[@]+"${MODEL_FLAG[@]}"} "$@" ) > "$RESULTS/$arm-$i.json" 2> "$RESULTS/$arm-$i.err" || true
    if [[ -s "$work/report.pdf" ]]; then
      cp "$work/report.pdf" "$RESULTS/$arm-$i.pdf"
    fi
    rm -rf "$work"
  done
}

run_arm baseline
run_arm rupa --plugin-dir "$NOVERIFY"
run_arm rupa-pertype --plugin-dir "$PERTYPE"
run_arm rupa-verify --plugin-dir "$ROOT/plugin"

python3 "$ROOT/bench/summarize.py" "$RESULTS"
