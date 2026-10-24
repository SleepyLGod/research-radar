#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/build/macos-engine"
DIST="$ROOT/dist/macos-engine"
SPEC="$ROOT/packaging/macos/research-radar-engine.spec"

for output_path in "$WORK" "$DIST"; do
  if [[ -e "$output_path" ]]; then
    /usr/bin/trash "$output_path"
  fi
done
/bin/mkdir -p "$WORK" "$DIST"

cd "$ROOT"
uv run --extra app-build pyinstaller \
  --noconfirm \
  --workpath "$WORK" \
  --distpath "$DIST" \
  "$SPEC"

ENGINE_APP="$DIST/ResearchRadarEngine.app"
ENGINE="$ENGINE_APP/Contents/MacOS/research-radar-engine"
if [[ ! -x "$ENGINE" ]]; then
  print -u2 "Frozen engine was not created at $ENGINE"
  exit 1
fi
print "$ENGINE_APP"
