#!/usr/bin/env bash
# Compare Claude Code cost on the same task across three arms:
#   baseline       no plugin: Claude writes the HTML/CSS and finds its own PDF tool
#   rupa           plugin, render only (the skill's Verify section is removed)
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

# The render-only arm uses a copy of the plugin whose skill stops before "## Verify".
NOVERIFY="$RESULTS/plugin-noverify"
cp -r "$ROOT/plugin" "$NOVERIFY"
awk '/^## Verify/ {skip=1} /^Do not add styling/ {skip=0} !skip' \
  "$ROOT/plugin/skills/render/SKILL.md" > "$NOVERIFY/skills/render/SKILL.md"

run_arm() {  # $1 = arm name, remaining args = extra claude flags
  local arm="$1"; shift
  for i in $(seq 1 "$RUNS"); do
    local work; work="$(mktemp -d)"
    echo "bench: $arm run $i" >&2
    ( cd "$work" && claude -p "$TASK" --output-format json --allowedTools "$TOOLS" \
        "${MODEL_FLAG[@]}" "$@" ) > "$RESULTS/$arm-$i.json" 2> "$RESULTS/$arm-$i.err" || true
    if [[ -s "$work/report.pdf" ]]; then
      cp "$work/report.pdf" "$RESULTS/$arm-$i.pdf"
    fi
    rm -rf "$work"
  done
}

run_arm baseline
run_arm rupa --plugin-dir "$NOVERIFY"
run_arm rupa-verify --plugin-dir "$ROOT/plugin"

python3 "$ROOT/bench/summarize.py" "$RESULTS"
