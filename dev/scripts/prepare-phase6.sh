#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/render-filebeat-ha-config.py"
"${SCRIPT_DIR}/generate-beats-pki.sh"

printf 'Configuration de la phase 6 preparee.\n'
