#!/usr/bin/env bash
# Attach the IDF serial monitor. Usage: scripts/monitor.sh [port]   (exit: Ctrl-])
set -euo pipefail
PORT="${1:-/dev/ttyUSB0}"
cd "$(dirname "$0")/../firmware"
. "$HOME/esp/v5.5.2/esp-idf/export.sh" >/dev/null
idf.py -p "$PORT" monitor
