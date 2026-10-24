#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRAMEWORKS="/Library/Developer/CommandLineTools/Library/Developer/Frameworks"
DEVELOPER_LIB="/Library/Developer/CommandLineTools/Library/Developer/usr/lib"
MODULE_CACHE="$ROOT/.build/swift-module-cache"
SCRATCH="$ROOT/.build/swift-scratch"
CACHE="$ROOT/.build/swift-cache"
CONFIG="$ROOT/.build/swift-config"
SECURITY="$ROOT/.build/swift-security"

mkdir -p "$MODULE_CACHE" "$SCRATCH" "$CACHE" "$CONFIG" "$SECURITY" "$ROOT/.build/swift-home"
export HOME="$ROOT/.build/swift-home"
export CLANG_MODULE_CACHE_PATH="$MODULE_CACHE"
export SWIFTPM_MODULECACHE_OVERRIDE="$MODULE_CACHE"

exec swift test \
  --no-parallel \
  --disable-sandbox \
  --enable-swift-testing \
  --disable-xctest \
  --package-path "$ROOT/apps/macos/ResearchRadar" \
  --scratch-path "$SCRATCH" \
  --cache-path "$CACHE" \
  --config-path "$CONFIG" \
  --security-path "$SECURITY" \
  -Xswiftc -F -Xswiftc "$FRAMEWORKS" \
  -Xlinker -F -Xlinker "$FRAMEWORKS" \
  -Xlinker -rpath -Xlinker "$FRAMEWORKS" \
  -Xlinker -rpath -Xlinker "$DEVELOPER_LIB" \
  "$@"
