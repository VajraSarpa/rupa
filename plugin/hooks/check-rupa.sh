#!/bin/sh
# SessionStart: tell Claude if the rupa CLI is missing or older than this
# plugin's skill expects. Prints nothing when all is well.
MIN=0.1.0
INSTALL="uv tool install --force git+https://github.com/VajraSarpa/rupa@v$MIN"

if ! command -v rupa >/dev/null 2>&1; then
  echo "rupa CLI not on PATH. Install it with: $INSTALL"
  exit 0
fi
have=$(rupa --version 2>/dev/null | awk '{print $2}')
lowest=$(printf '%s\n%s\n' "$MIN" "$have" | sort -V | head -n1)
if [ -z "$have" ] || [ "$lowest" != "$MIN" ]; then
  echo "rupa CLI ${have:-unknown} is older than $MIN, which the rupa:render skill needs. Upgrade with: $INSTALL"
fi
exit 0
