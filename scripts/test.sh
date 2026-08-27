#!/usr/bin/env bash
set -euo pipefail

repo="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$repo/src"

python3 -m unittest discover -s "$repo/tests" -v
bash -n "$repo/platforms/lubuntu-24.04/install.sh"
bash -n "$repo/platforms/proxmox/readonly-preflight.sh"
