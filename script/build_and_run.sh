#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-run}"

case "$MODE" in
    run|--verify|verify)
        ;;
    --debug|debug)
        export VMCTL_BUILD_CONFIGURATION=debug
        ;;
    --logs|logs|--telemetry|telemetry)
        ;;
    *)
        echo "usage: $0 [run|--debug|--logs|--telemetry|--verify]" >&2
        exit 2
        ;;
esac

"$ROOT_DIR/script/install-from-source.sh"

if [[ "$MODE" == "--logs" || "$MODE" == "logs" ]]; then
    /usr/bin/log show --last 5m --info --style compact --predicate 'process == "VMRunner"'
elif [[ "$MODE" == "--telemetry" || "$MODE" == "telemetry" ]]; then
    /usr/bin/log show --last 5m --info --style compact --predicate 'process == "VMRunner"'
fi

echo "Build, tests, installation, and diagnostics completed. Run 'vmctl start' when ready."
