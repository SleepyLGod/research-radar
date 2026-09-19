#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SWIFT_RELEASE="$ROOT/.build/swift-release/arm64-apple-macosx/release"
SWIFT_BINARY="$SWIFT_RELEASE/ResearchRadar"
PDF_HELPER="$SWIFT_RELEASE/ResearchRadarPDFHelper"
RESOURCE_BUNDLE="$SWIFT_RELEASE/ResearchRadar_ResearchRadarAppFeature.bundle"
SOURCE_ENGINE="$ROOT/dist/macos-engine/ResearchRadarEngine.app"
APP="$ROOT/dist/ResearchRadar.app"
BUILD_MODE="${1:---development}"
if [[ "$BUILD_MODE" != "--development" && "$BUILD_MODE" != "--production" ]]; then
  print -u2 "Usage: assemble_macos_app.sh [--development|--production]"
  exit 2
fi

for required in "$SWIFT_BINARY" "$PDF_HELPER" "$RESOURCE_BUNDLE" "$SOURCE_ENGINE"; do
  if [[ ! -e "$required" ]]; then
    print -u2 "Missing staged input: $required"
    exit 1
  fi
done
if [[ -e "$APP" ]]; then
  /usr/bin/trash "$APP"
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Helpers"
/usr/bin/ditto "$ROOT/packaging/macos/Info.plist" "$APP/Contents/Info.plist"
if [[ "$BUILD_MODE" == "--production" ]]; then
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier ai.research-radar.macos' "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c 'Set :ResearchRadarDevelopmentBuild false' "$APP/Contents/Info.plist"
fi
/usr/bin/ditto "$SWIFT_BINARY" "$APP/Contents/MacOS/ResearchRadar"
/usr/bin/ditto "$PDF_HELPER" "$APP/Contents/Helpers/ResearchRadarPDFHelper"
/usr/bin/ditto "$RESOURCE_BUNDLE" "$APP/Contents/Resources/ResearchRadar_ResearchRadarAppFeature.bundle"
/usr/bin/ditto "$SOURCE_ENGINE" "$APP/Contents/Helpers/ResearchRadarEngine.app"
chmod 755 "$APP/Contents/MacOS/ResearchRadar"
chmod 755 "$APP/Contents/Helpers/ResearchRadarPDFHelper"
/usr/bin/strip -S "$APP/Contents/MacOS/ResearchRadar"
/usr/bin/strip -S "$APP/Contents/Helpers/ResearchRadarPDFHelper"

"$ROOT/.venv/bin/python" "$ROOT/script/verify_macos_bundle.py" \
  --source-engine "$SOURCE_ENGINE" \
  --app "$APP"
"$ROOT/.venv/bin/python" "$ROOT/script/sign_macos_bundle.py" "$APP"
/usr/bin/codesign --verify --deep --strict --verbose=2 "$APP"
print "$APP"
