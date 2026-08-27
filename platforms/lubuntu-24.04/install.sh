#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
dry_run=0
source_dir="/media/ubuntu/MapleStoryClassic"

usage() {
  printf 'Usage: %s [--dry-run] [--source PATH]\n' "$0" >&2
  exit 2
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --source)
      [[ "$#" -ge 2 ]] || usage
      source_dir="$2"
      shift 2
      ;;
    *) usage ;;
  esac
done

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$repo/src"

if [[ "$dry_run" -eq 1 ]]; then
  exec python3 -m msclassic.installer \
    --dry-run \
    --platform lubuntu-24.04 \
    --source "$source_dir" \
    --lock "$repo/versions.lock"
fi

if [[ "$EUID" -eq 0 ]]; then
  privilege=()
elif command -v sudo >/dev/null 2>&1; then
  privilege=(sudo)
else
  printf 'ERROR: guest package installation requires root or sudo.\n' >&2
  exit 1
fi

# Stage 1: install only the selected distribution adapter's bootstrap packages.
if ! dpkg --print-foreign-architectures | grep -Fxq i386; then
  "${privilege[@]}" dpkg --add-architecture i386
fi
mapfile -t packages < <(
  python3 -c \
    'from msclassic.platforms import LUBUNTU_2404; print(*LUBUNTU_2404.package_names, sep="\n")'
)
"${privilege[@]}" apt-get update
"${privilege[@]}" apt-get install -y "${packages[@]}"
"${privilege[@]}" locale-gen zh_TW.UTF-8
chromium_policy_dir="/etc/chromium/policies/managed"
"${privilege[@]}" install -d -m 0755 "$chromium_policy_dir"
"${privilege[@]}" install -m 0644 \
  "$repo/platforms/lubuntu-24.04/chromium-policy.json" \
  "$chromium_policy_dir/msclassic-linux.json"

# Stage 2: graphics-gated, checksum-locked application installation.
python3 -m msclassic.cli doctor --preflight --json
exec python3 -m msclassic.cli install \
  --platform lubuntu-24.04 \
  --source "$source_dir"
