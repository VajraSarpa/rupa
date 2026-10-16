#!/usr/bin/env bash
# Compare Claude Code cost on the same task across four arms:
#   baseline       no plugin: Claude writes the HTML/CSS and finds its own PDF tool
#   rupa           plugin, render only (the skill's Verify section is removed)
#   rupa-flagged   plugin, verify with sheets only for pages a code check flags
#   rupa-verify    plugin as shipped: render, then verify with a visual review
#
# Usage: bench/bench.sh [runs]        default 1 run per arm (a pilot)
#        MODEL=claude-sonnet-5-5 bench/bench.sh 3
# Each run starts in a fresh empty directory, so no arm can see this repo.
set -euo pipefail

RUNS="${1:-1}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RESULTS="$ROOT/bench/results/$(date +%Y%m%d-%H%M%S)"
TASK='Write a 2-page PDF report on the AWS Well-Architected security pillar, saved as report.pdf in the current directory.'
TOOLS="Bash Write Read Edit Skill"
MODEL_FLAG=()
[[ -n "${MODEL:-}" ]] && MODEL_FLAG=(--model "$MODEL")

mkdir -p "$RESULTS"
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

# Flagged only: verify makes sheets just for pages a code check flags.
FLAGGED="$RESULTS/plugin-flagged"
plugin_copy "$FLAGGED"
sed 's/`rupa verify out\/report.pdf`/`rupa verify --sample flagged out\/report.pdf`/' \
  "$SKILL" > "$FLAGGED/skills/render/SKILL.md"
grep -q -- '--sample flagged' "$FLAGGED/skills/render/SKILL.md" \
  || { echo "bench: could not make the flagged skill; SKILL.md changed?" >&2; exit 2; }

run_arm() {  # $1 = arm name, remaining args = extra claude flags
  local arm="$1"; shift
  for i in $(seq 1 "$RUNS"); do
    local work; work="$(mktemp -d)"
    echo "bench: $arm run $i" >&2
    ( cd "$work" && claude -p "$TASK" --output-format json --allowedTools "$TOOLS" \
        ${MODEL_FLAG[@]+"${MODEL_FLAG[@]}"} "$@" ) > "$RESULTS/$arm-$i.json" 2> "$RESULTS/$arm-$i.err" || true
    if [[ -s "$work/report.pdf" ]]; then
      cp "$work/report.pdf" "$RESULTS/$arm-$i.pdf"
    fi
    rm -rf "$work"
  done
}

run_arm baseline
run_arm rupa --plugin-dir "$NOVERIFY"
run_arm rupa-flagged --plugin-dir "$FLAGGED"
run_arm rupa-verify --plugin-dir "$ROOT/plugin"

python3 "$ROOT/bench/summarize.py" "$RESULTS"
