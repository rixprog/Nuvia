#!/usr/bin/env bash
# Build + flash the firmware. Usage: scripts/flash.sh [port]
set -euo pipefail
PORT="${1:-/dev/ttyUSB0}"
cd "$(dirname "$0")/../firmware"
. "$HOME/esp/v5.5.2/esp-idf/export.sh" >/dev/null
idf.py -p "$PORT" -b 460800 build flash
