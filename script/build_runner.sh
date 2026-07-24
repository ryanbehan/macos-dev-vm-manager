#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${VMCTL_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNNER_DIR="$ROOT_DIR/runner"
APP_BUNDLE="${VMCTL_APP_BUNDLE:-$ROOT_DIR/app/VMRunner.app}"
CONFIGURATION="${VMCTL_BUILD_CONFIGURATION:-release}"
SIGNING_MODE="${VMCTL_SIGNING_MODE:-adhoc}"
IDENTITY="${VMCTL_CODESIGN_IDENTITY:-}"
SWIFT_BIN="${VMCTL_SWIFT_BIN:-$(xcrun --find swift)}"
CODESIGN_BIN="${VMCTL_CODESIGN_BIN:-/usr/bin/codesign}"
SECURITY_BIN="${VMCTL_SECURITY_BIN:-/usr/bin/security}"
STRIP_BIN="${VMCTL_STRIP_BIN:-/usr/bin/strip}"
PYTHON_BIN="${VMCTL_PYTHON_BIN:-$(command -v python3)}"
SOURCE_PREFIX_MAP="${VMCTL_SOURCE_PREFIX_MAP:-$ROOT_DIR=/vmctl-source}"

usage() {
    echo "usage: $0 [--signing adhoc|development|developer-id] [--identity IDENTITY]" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --signing)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            SIGNING_MODE="$2"
            shift 2
            ;;
        --identity)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            IDENTITY="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
done

case "$SIGNING_MODE" in
    adhoc)
        SIGNING_IDENTITY="-"
        TIMESTAMP_ARGUMENT="--timestamp=none"
        if [[ -n "$IDENTITY" ]]; then
            echo "--identity is not valid with ad hoc signing." >&2
            exit 2
        fi
        ;;
    development)
        [[ -n "$IDENTITY" ]] || {
            echo "Development signing requires --identity or VMCTL_CODESIGN_IDENTITY." >&2
            exit 2
        }
        if ! "$SECURITY_BIN" find-identity -v -p codesigning | grep -Fq "\"$IDENTITY\""; then
            echo "Signing identity is unavailable." >&2
            exit 1
        fi
        SIGNING_IDENTITY="$IDENTITY"
        TIMESTAMP_ARGUMENT="--timestamp=none"
        ;;
    developer-id)
        [[ -n "$IDENTITY" ]] || {
            echo "Developer ID signing requires an explicit identity." >&2
            exit 2
        }
        if [[ "${VMCTL_TRUSTED_RELEASE:-0}" != "1" ]]; then
            echo "Developer ID signing is restricted to an explicitly trusted release context." >&2
            exit 1
        fi
        if ! "$SECURITY_BIN" find-identity -v -p codesigning | grep -Fq "\"$IDENTITY\""; then
            echo "Signing identity is unavailable." >&2
            exit 1
        fi
        SIGNING_IDENTITY="$IDENTITY"
        TIMESTAMP_ARGUMENT="--timestamp"
        ;;
    *)
        echo "Unknown signing mode: $SIGNING_MODE" >&2
        exit 2
        ;;
esac

SWIFT_BUILD_ARGUMENTS=(
    --package-path "$RUNNER_DIR"
    -c "$CONFIGURATION"
    -Xswiftc -debug-prefix-map
    -Xswiftc "$SOURCE_PREFIX_MAP"
    -Xswiftc -file-prefix-map
    -Xswiftc "$SOURCE_PREFIX_MAP"
)
if [[ "$CONFIGURATION" == "release" ]]; then
    SWIFT_BUILD_ARGUMENTS+=(-Xswiftc -gnone)
fi
"$SWIFT_BIN" build "${SWIFT_BUILD_ARGUMENTS[@]}"
BUILD_DIR="$("$SWIFT_BIN" build "${SWIFT_BUILD_ARGUMENTS[@]}" --show-bin-path)"
RUNNER_BINARY="$BUILD_DIR/VMRunner"
INSTALLER_BINARY="$BUILD_DIR/VMInstaller"
for executable in "$RUNNER_BINARY" "$INSTALLER_BINARY"; do
    if [[ ! -x "$executable" ]]; then
        echo "Built executable is missing: $executable" >&2
        exit 1
    fi
done

APP_PARENT="$(dirname "$APP_BUNDLE")"
mkdir -p "$APP_PARENT"
TEMP_APP="$APP_PARENT/.VMRunner.app.staging.$$"
BACKUP_APP="$APP_PARENT/.VMRunner.app.previous.$$"
cleanup() {
    rm -rf "$TEMP_APP"
    if [[ -e "$BACKUP_APP" ]]; then
        if [[ ! -e "$APP_BUNDLE" ]]; then
            mv "$BACKUP_APP" "$APP_BUNDLE"
        else
            rm -rf "$BACKUP_APP"
        fi
    fi
}
trap cleanup EXIT

mkdir -p "$TEMP_APP/Contents/MacOS" "$TEMP_APP/Contents/Helpers"
cp "$RUNNER_BINARY" "$TEMP_APP/Contents/MacOS/VMRunner"
cp "$INSTALLER_BINARY" "$TEMP_APP/Contents/Helpers/VMInstaller"
chmod 755 "$TEMP_APP/Contents/MacOS/VMRunner" "$TEMP_APP/Contents/Helpers/VMInstaller"
"$STRIP_BIN" -S "$TEMP_APP/Contents/MacOS/VMRunner"
"$STRIP_BIN" -S "$TEMP_APP/Contents/Helpers/VMInstaller"

VERSION="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
if [[ "$("$INSTALLER_BINARY" --version)" != "$VERSION protocol=1" ]]; then
    echo "VMInstaller version/protocol does not match VERSION." >&2
    exit 1
fi
cat >"$TEMP_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>VMRunner</string>
  <key>CFBundleIdentifier</key>
  <string>dev.vmctl.runner</string>
  <key>CFBundleName</key>
  <string>VMRunner</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>$VERSION</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>26.0</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

# This directory was created by this build. Clear inherited metadata only before signing.
xattr -cr "$TEMP_APP"
"$CODESIGN_BIN" --force --options runtime "$TIMESTAMP_ARGUMENT" \
    --identifier dev.vmctl.installer \
    --sign "$SIGNING_IDENTITY" \
    --entitlements "$RUNNER_DIR/VMInstaller.entitlements" \
    "$TEMP_APP/Contents/Helpers/VMInstaller"
"$CODESIGN_BIN" --force --options runtime "$TIMESTAMP_ARGUMENT" \
    --sign "$SIGNING_IDENTITY" \
    --entitlements "$RUNNER_DIR/VMRunner.entitlements" \
    "$TEMP_APP"

"$PYTHON_BIN" "$ROOT_DIR/script/verify_app.py" "$TEMP_APP"

if [[ -e "$APP_BUNDLE" ]]; then
    mv "$APP_BUNDLE" "$BACKUP_APP"
fi
mv "$TEMP_APP" "$APP_BUNDLE"
for _ in 1 2 3 4 5; do
    xattr -d com.apple.FinderInfo "$APP_BUNDLE" 2>/dev/null || true
    xattr -d 'com.apple.fileprovider.fpfs#P' "$APP_BUNDLE" 2>/dev/null || true
    if "$PYTHON_BIN" "$ROOT_DIR/script/verify_app.py" "$APP_BUNDLE"; then
        FINAL_VERIFIED=1
        break
    fi
    sleep 0.1
done
if [[ "${FINAL_VERIFIED:-0}" != "1" ]]; then
    "$PYTHON_BIN" "$ROOT_DIR/script/verify_app.py" "$APP_BUNDLE"
fi
rm -rf "$BACKUP_APP"
trap - EXIT
echo "Staged and verified ($SIGNING_MODE): $APP_BUNDLE"
