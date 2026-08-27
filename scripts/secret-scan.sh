#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-$repo}"
uri_pattern="(nexonplug|ngm)://[?[:alnum:]%][^[:space:]]+"
secret_names="passarg|otp|cookie|authorization|serviceaccount|token"
named_pattern="(${secret_names})[=:][^[:space:],;}]+"

if rg -n -i -e "$uri_pattern" -e "$named_pattern" "$target" \
  --glob '!docs/superpowers/**' \
  --glob '!tests/**' \
  --glob '!src/msclassic/redaction.py' \
  --glob '!.git/**'; then
  printf 'ERROR: possible authenticated launch material found.\n' >&2
  exit 1
fi
printf 'Secret scan passed: no authenticated launch material found.\n'
