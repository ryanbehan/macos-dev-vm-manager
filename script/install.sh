#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "script/install.sh is a compatibility entry point; using install-from-source.sh." >&2
exec "$ROOT_DIR/script/install-from-source.sh" "$@"
