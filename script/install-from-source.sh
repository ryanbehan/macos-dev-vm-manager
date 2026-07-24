#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${VMCTL_PYTHON_BIN:-$(command -v python3 || true)}"
HOME_DIR="${HOME:?HOME is required}"
INSTALL_ROOT="${VMCTL_INSTALL_ROOT:-$HOME_DIR/Library/Application Support/vmctl}"
DATA_ROOT="${VMCTL_DATA_ROOT:-$INSTALL_ROOT/data}"
LAUNCHER="${VMCTL_LAUNCHER_PATH:-$HOME_DIR/.local/bin/vmctl}"
SIGNING_MODE="${VMCTL_SIGNING_MODE:-adhoc}"
IDENTITY="${VMCTL_CODESIGN_IDENTITY:-}"
SKIP_TESTS=0

usage() {
    echo "usage: $0 [--skip-tests] [--signing adhoc|development] [--identity IDENTITY]" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
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

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Python 3.10 or newer is required." >&2
    exit 1
fi
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 or newer is required; detected: $("$PYTHON_BIN" --version 2>&1)" >&2
    exit 1
fi

PYTHONPATH="$ROOT_DIR/src" "$PYTHON_BIN" -m vmctl.preflight \
    --source-root "$ROOT_DIR" \
    --install-root "$INSTALL_ROOT" \
    --data-root "$DATA_ROOT" \
    --launcher "$LAUNCHER"

if [[ "$SKIP_TESTS" != "1" ]]; then
    PYTHONPATH="$ROOT_DIR/src" "$PYTHON_BIN" -m unittest discover -s "$ROOT_DIR/tests"
    xcrun swift test --package-path "$ROOT_DIR/runner"
    "$PYTHON_BIN" "$ROOT_DIR/script/check_release_hygiene.py" --allow-author
fi

VERSION="$(tr -d '[:space:]' <"$ROOT_DIR/VERSION")"
SOURCE_DIGEST="$("$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
digest = hashlib.sha256()
for relative in sorted(
    [
        Path("VERSION"),
        *Path("src").rglob("*"),
        *Path("runner").rglob("*"),
        *Path("script").rglob("*"),
    ]
):
    path = root / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or any(part in {".build", "__pycache__"} for part in relative.parts)
    ):
        continue
    digest.update(relative.as_posix().encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
print(digest.hexdigest())
PY
)"
RELEASES="$INSTALL_ROOT/releases"
FINAL_RELEASE="$RELEASES/$VERSION"
STAGED_RELEASE="$RELEASES/.staging-$VERSION-$$"
CURRENT_LINK="$INSTALL_ROOT/current"
BUILD_ROOT="$HOME_DIR/Library/Caches/vmctl/builds/source-$VERSION-$$"
BUILD_APP="$BUILD_ROOT/VMRunner.app"

REUSE_RELEASE=0
if [[ -e "$FINAL_RELEASE" || -L "$FINAL_RELEASE" ]]; then
    if "$PYTHON_BIN" - "$FINAL_RELEASE/release.json" "$VERSION" "$SOURCE_DIGEST" "$SIGNING_MODE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    value = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
expected = {
    "version": sys.argv[2],
    "sourceDigest": sys.argv[3],
    "signingMode": sys.argv[4],
}
raise SystemExit(0 if all(value.get(key) == item for key, item in expected.items()) else 1)
PY
    then
        REUSE_RELEASE=1
        echo "Release $VERSION already matches this source; reusing it."
    else
        echo "Release $VERSION exists but does not match this source/signing mode." >&2
        echo "Bump VERSION or remove only the unreferenced conflicting program release." >&2
        exit 1
    fi
fi

cleanup() {
    rm -rf "$STAGED_RELEASE" "$BUILD_ROOT"
}
trap cleanup EXIT

if [[ "$REUSE_RELEASE" != "1" ]]; then
    mkdir -p "$BUILD_ROOT"
    chmod 700 "$BUILD_ROOT"
    BUILD_ARGUMENTS=(--signing "$SIGNING_MODE")
    if [[ -n "$IDENTITY" ]]; then
        BUILD_ARGUMENTS+=(--identity "$IDENTITY")
    fi
    VMCTL_PYTHON_BIN="$PYTHON_BIN" \
        VMCTL_APP_BUNDLE="$BUILD_APP" \
        "$ROOT_DIR/script/build_runner.sh" "${BUILD_ARGUMENTS[@]}"
    mkdir -p "$STAGED_RELEASE/bin" "$STAGED_RELEASE/lib" "$STAGED_RELEASE/libexec"
    chmod 700 "$STAGED_RELEASE"
    mkdir -p "$STAGED_RELEASE/lib/vmctl"
    cp "$ROOT_DIR"/src/vmctl/*.py "$STAGED_RELEASE/lib/vmctl/"
    cp -R -X "$BUILD_APP" "$STAGED_RELEASE/libexec/VMRunner.app"

    cat >"$STAGED_RELEASE/bin/vmctl" <<LAUNCHER_SCRIPT
#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="$PYTHON_BIN"
if ! "\$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "vmctl requires Python 3.10 or newer. Reinstall from source." >&2
    exit 7
fi
export PYTHONPATH="$FINAL_RELEASE/lib"
exec "\$PYTHON_BIN" -m vmctl "\$@"
LAUNCHER_SCRIPT
    chmod 755 "$STAGED_RELEASE/bin/vmctl"

    "$PYTHON_BIN" - "$STAGED_RELEASE/release.json" "$VERSION" "$SIGNING_MODE" "$SOURCE_DIGEST" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
value = {
    "schemaVersion": 1,
    "version": sys.argv[2],
    "channel": "source",
    "pythonMinimum": "3.10",
    "runnerProtocol": 1,
    "bundleIdentifier": "dev.vmctl.runner",
    "signingMode": sys.argv[3],
    "sourceDigest": sys.argv[4],
}
path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
PY

    "$PYTHON_BIN" "$ROOT_DIR/script/verify_app.py" "$STAGED_RELEASE/libexec/VMRunner.app"
    mkdir -p "$RELEASES"
    chmod 700 "$INSTALL_ROOT" "$RELEASES"
    mv "$STAGED_RELEASE" "$FINAL_RELEASE"
fi

TEMP_CURRENT="$INSTALL_ROOT/.current-$$"
ln -s "releases/$VERSION" "$TEMP_CURRENT"
mv -f "$TEMP_CURRENT" "$CURRENT_LINK"

mkdir -p "$(dirname "$LAUNCHER")"
TEMP_LAUNCHER="$(dirname "$LAUNCHER")/.vmctl-link-$$"
ln -s "$CURRENT_LINK/bin/vmctl" "$TEMP_LAUNCHER"
mv -f "$TEMP_LAUNCHER" "$LAUNCHER"

"$PYTHON_BIN" - "$INSTALL_ROOT/install-manifest.json" "$INSTALL_ROOT" "$LAUNCHER" "$VERSION" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
value = {
    "schemaVersion": 1,
    "installRoot": sys.argv[2],
    "launcher": sys.argv[3],
    "activeVersion": sys.argv[4],
    "ownedProgramPaths": [
        str(Path(sys.argv[2]) / "current"),
        str(Path(sys.argv[2]) / "releases"),
        sys.argv[3],
    ],
    "ownedDataPaths": [],
}
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
descriptor, temporary = tempfile.mkstemp(prefix=".install-manifest.", dir=path.parent)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2, sort_keys=True)
    handle.write("\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, path)
os.chmod(path, 0o600)
PY

cleanup
trap - EXIT
echo "Installed vmctl $VERSION at $FINAL_RELEASE"
echo "Launcher: $LAUNCHER"
if [[ ":$PATH:" != *":$(dirname "$LAUNCHER"):"* ]]; then
    echo "NEXT Add this directory to PATH: $(dirname "$LAUNCHER")"
fi
"$LAUNCHER" --version
"$LAUNCHER" doctor
