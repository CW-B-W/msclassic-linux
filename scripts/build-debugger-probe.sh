#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output=""

if [[ "$#" -eq 2 && "$1" == "--output" ]]; then
  output="$2"
else
  printf 'Usage: %s --output /absolute/path/suspend-context-probe.exe\n' "$0" >&2
  exit 2
fi

[[ "$output" == /* && "$output" == *.exe ]] || {
  printf 'ERROR: output must be an absolute .exe path.\n' >&2
  exit 2
}
[[ ! -e "$output" ]] || {
  printf 'ERROR: output already exists; refusing to overwrite it.\n' >&2
  exit 1
}
output_parent="$(dirname "$output")"
[[ -d "$output_parent" ]] || {
  printf 'ERROR: output directory does not exist.\n' >&2
  exit 1
}

compiler="${MSCLASSIC_MINGW_CC:-x86_64-w64-mingw32-gcc}"
command -v "$compiler" >/dev/null || {
  printf 'ERROR: x86-64 MinGW compiler is unavailable.\n' >&2
  exit 1
}

temporary="$(mktemp "$output_parent/.suspend-context-probe-XXXXXX.exe")"
trap 'rm -f "$temporary"' EXIT
"$compiler" \
  -std=c11 -O2 -Wall -Wextra -Werror \
  "$repo/diagnostics/suspend-context-probe.c" \
  -o "$temporary"
chmod 0700 "$temporary"
mv "$temporary" "$output"
trap - EXIT
printf 'Debugger compatibility probe created: %s\n' "$output"
