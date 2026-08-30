#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODULE_CACHE="$ROOT/.build/swift-module-cache"
RELEASE_SCRATCH="$ROOT/.build/swift-release"

if [[ "$(uname -m)" != "arm64" ]]; then
  print -u2 "Task 1 supports Apple Silicon arm64 only."
  exit 1
fi
SWIFT_VERSION="$(swift --version | head -n 1)"
SDK_VERSION="$(xcrun --show-sdk-version)"
SWIFT_NUMBER="$(print -r -- "$SWIFT_VERSION" | /usr/bin/sed -nE 's/.*Swift version ([0-9]+\.[0-9]+).*/\1/p')"
SWIFT_MAJOR="${SWIFT_NUMBER%%.*}"
SWIFT_MINOR="${SWIFT_NUMBER#*.}"
if [[ -z "$SWIFT_NUMBER" ]] || (( SWIFT_MAJOR < 6 || (SWIFT_MAJOR == 6 && SWIFT_MINOR < 3) )); then
  print -u2 "Swift 6.3 or newer is required: $SWIFT_VERSION"
  exit 1
fi
if [[ "$SDK_VERSION" != 26.* ]]; then
  print -u2 "A macOS 26 SDK is required: $SDK_VERSION"
  exit 1
fi

mkdir -p "$MODULE_CACHE" "$RELEASE_SCRATCH"
export CLANG_MODULE_CACHE_PATH="$MODULE_CACHE"
export SWIFTPM_MODULECACHE_OVERRIDE="$MODULE_CACHE"

cd "$ROOT"
uv sync --extra dev --extra app-build
"$ROOT/script/swift_test.sh"
swift build \
  --disable-sandbox \
  --package-path "$ROOT/apps/macos/ResearchRadar" \
  --scratch-path "$RELEASE_SCRATCH" \
  --configuration release \
  -Xswiftc -DRESEARCH_RADAR_APP_BUNDLE \
  --product ResearchRadar
swift build \
  --disable-sandbox \
  --package-path "$ROOT/apps/macos/ResearchRadar" \
  --scratch-path "$RELEASE_SCRATCH" \
  --configuration release \
  --product ResearchRadarPDFHelper
"$ROOT/script/build_macos_engine.sh"
"$ROOT/script/assemble_macos_app.sh"

ENGINE="$ROOT/dist/ResearchRadar.app/Contents/Helpers/ResearchRadarEngine.app/Contents/MacOS/research-radar-engine"
"$ROOT/.venv/bin/python" "$ROOT/script/run_macos_engine_smoke.py" \
  --engine "$ENGINE" \
  --root "$ROOT/.build/frozen-engine-smoke"

print "$ROOT/dist/ResearchRadar.app"
