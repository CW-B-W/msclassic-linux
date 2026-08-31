#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base_runtime=""
output_runtime=""
build_cache=""

usage() {
  printf 'Usage: %s --base-runtime PATH --output PATH --cache PATH\n' "$0" >&2
  exit 2
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --base-runtime)
      [[ "$#" -ge 2 ]] || usage
      base_runtime="$2"
      shift 2
      ;;
    --output)
      [[ "$#" -ge 2 ]] || usage
      output_runtime="$2"
      shift 2
      ;;
    --cache)
      [[ "$#" -ge 2 ]] || usage
      build_cache="$2"
      shift 2
      ;;
    *) usage ;;
  esac
done

[[ -n "$base_runtime" && -n "$output_runtime" && -n "$build_cache" ]] || usage
base_runtime="$(realpath "$base_runtime")"
output_runtime="$(realpath -m "$output_runtime")"
build_cache="$(realpath -m "$build_cache")"
required_build_cache="/home/ubuntu/.cache/msclassic-build"
[[ "$build_cache" == "$required_build_cache" ]] || {
  printf 'ERROR: input diagnostic Wine requires build cache %s.\n' "$required_build_cache" >&2
  exit 1
}

source_url="https://github.com/Kron4ek/wine-tkg.git"
source_commit="4b12965ca7e78b8e45eee5f835c72963b3ce351d"
patch_file="$project_root/patches/wine-11.10-msclassic-input-diagnostic.patch"
expected_patch_sha="fbd10d91030ee42aea469d01fc123fb2f3fe6defabb982960b1754933fb26448"
expected_base_winex11_sha="5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5"
expected_base_imm32_sha="989c1e1d2358ae47b3fe700631551a1b4563e4b2db738d26060c97a37f11aedf"
expected_base_ntdll_sha="2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d"
expected_winex11_sha="846f33382d663be8e4d92d0c533044c4b89f4c5c44a347fbf007221b12024bd8"
expected_winex11_size="545712"
expected_imm32_sha="6ffb4ef5528e48d6e79d7d9da0fe7d0d86f2cfa3ece0847f886942583f28a5aa"
expected_imm32_size="232390"
source_dir="$build_cache/wine-tkg-inputdiag-11.10"
build_dir="$build_cache/wine-tkg-inputdiag-build-11.10-v2"
base_winex11="$base_runtime/lib/wine/x86_64-unix/winex11.so"
base_imm32="$base_runtime/lib/wine/x86_64-windows/imm32.dll"
base_ntdll="$base_runtime/lib/wine/x86_64-windows/ntdll.dll"
built_winex11="$build_dir/dlls/winex11.drv/winex11.so"
built_imm32="$build_dir/dlls/imm32/x86_64-windows/imm32.dll"

for command in git make gcc g++ bison flex strip sha256sum x86_64-w64-mingw32-objcopy dd od tr; do
  command -v "$command" >/dev/null || {
    printf 'ERROR: missing input-diagnostic build command: %s\n' "$command" >&2
    exit 1
  }
done

[[ -d "$base_runtime" && -x "$base_runtime/bin/wine" && -x "$base_runtime/bin/wineserver" ]] || {
  printf 'ERROR: known-good patched Wine runtime is unavailable.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_base_winex11_sha" "$base_winex11" | sha256sum --check --status || {
  printf 'ERROR: base Wine X11 driver does not match the locked input.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_base_imm32_sha" "$base_imm32" | sha256sum --check --status || {
  printf 'ERROR: base Wine IMM32 does not match the locked input.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_base_ntdll_sha" "$base_ntdll" | sha256sum --check --status || {
  printf 'ERROR: base patched NTDLL does not match the locked input.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_patch_sha" "$patch_file" | sha256sum --check --status || {
  printf 'ERROR: input diagnostic patch failed verification.\n' >&2
  exit 1
}
[[ ! -e "$output_runtime" ]] || {
  printf 'ERROR: diagnostic Wine output exists; refusing to overwrite it.\n' >&2
  exit 1
}

mkdir -p -m 700 "$build_cache"
if [[ ! -d "$source_dir/.git" ]]; then
  clone_dir="$(mktemp -d "$build_cache/.wine-inputdiag-source-XXXXXX")"
  trap 'rm -rf "$clone_dir"' EXIT
  git -C "$clone_dir" init --quiet
  git -C "$clone_dir" remote add origin "$source_url"
  git -C "$clone_dir" fetch --quiet --depth=1 origin "$source_commit"
  git -C "$clone_dir" checkout --quiet --detach FETCH_HEAD
  mv "$clone_dir" "$source_dir"
  trap - EXIT
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$source_commit" ]] || {
  printf 'ERROR: cached input-diagnostic source commit is invalid.\n' >&2
  exit 1
}

if ! git -C "$source_dir" diff --quiet || [[ -n "$(git -C "$source_dir" status --porcelain --untracked-files=normal)" ]]; then
  if git -C "$source_dir" apply --reverse --check "$patch_file"; then
    git -C "$source_dir" apply --reverse "$patch_file"
  fi
fi
git -C "$source_dir" diff --quiet
[[ -z "$(git -C "$source_dir" status --porcelain --untracked-files=normal)" ]] || {
  printf 'ERROR: cached input-diagnostic source has unrelated changes.\n' >&2
  exit 1
}
git -C "$source_dir" apply --check "$patch_file"
git -C "$source_dir" apply "$patch_file"
patch_applied=1
staged_winex11=""
staged_imm32=""
staged_runtime=""
cleanup() {
  if [[ "${patch_applied:-0}" == 1 ]]; then
    git -C "$source_dir" apply --reverse "$patch_file" >/dev/null 2>&1 || true
  fi
  [[ -z "$staged_winex11" || ! -e "$staged_winex11" ]] || rm -f "$staged_winex11"
  [[ -z "$staged_imm32" || ! -e "$staged_imm32" ]] || rm -f "$staged_imm32"
  [[ -z "$staged_runtime" || ! -d "$staged_runtime" ]] || rm -rf "$staged_runtime"
}
trap cleanup EXIT

mkdir -p -m 700 "$build_dir"
if [[ ! -f "$build_dir/Makefile" ]]; then
  (
    cd "$build_dir"
    "$source_dir/configure" \
      --enable-win64 \
      --without-wayland \
      --without-freetype \
      --without-gnutls
  )
fi
make -C "$build_dir" -j"$(getconf _NPROCESSORS_ONLN)" \
  dlls/winex11.drv/winex11.so \
  dlls/imm32/x86_64-windows/imm32.dll

staged_winex11="$(mktemp "$build_cache/.winex11-inputdiag-XXXXXX.so")"
cp "$built_winex11" "$staged_winex11"
strip --strip-debug "$staged_winex11"
[[ "$(stat -c '%s' "$staged_winex11")" == "$expected_winex11_size" ]] || {
  printf 'ERROR: input diagnostic X11 driver size is not reproducible.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_winex11_sha" "$staged_winex11" | sha256sum --check --status || {
  printf 'ERROR: input diagnostic X11 driver is not reproducible.\n' >&2
  exit 1
}

staged_imm32="$(mktemp "$build_cache/.imm32-inputdiag-XXXXXX.dll")"
cp "$built_imm32" "$staged_imm32"
strip --strip-debug "$staged_imm32"
x86_64-w64-mingw32-objcopy --remove-section .buildid "$staged_imm32"
[[ "$(od -An -j 128 -N 4 -t x1 "$staged_imm32" | tr -d ' \n')" == "50450000" ]] || {
  printf 'ERROR: input diagnostic IMM32 has an unexpected PE header.\n' >&2
  exit 1
}
printf '\0\0\0\0' | dd of="$staged_imm32" bs=1 seek=136 conv=notrunc status=none
printf '\0\0\0\0' | dd of="$staged_imm32" bs=1 seek=216 conv=notrunc status=none
[[ "$(stat -c '%s' "$staged_imm32")" == "$expected_imm32_size" ]] || {
  printf 'ERROR: input diagnostic IMM32 size is not reproducible.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_imm32_sha" "$staged_imm32" | sha256sum --check --status || {
  printf 'ERROR: input diagnostic IMM32 is not reproducible.\n' >&2
  exit 1
}

output_parent="$(dirname "$output_runtime")"
mkdir -p -m 700 "$output_parent"
staged_runtime="$(mktemp -d "$output_parent/.wine-inputdiag-runtime-XXXXXX")"
cp -a --reflink=auto "$base_runtime/." "$staged_runtime/"
install -m 0644 "$staged_winex11" "$staged_runtime/lib/wine/x86_64-unix/winex11.so"
install -m 0644 "$staged_imm32" "$staged_runtime/lib/wine/x86_64-windows/imm32.dll"
printf '%s\n' \
  '{"base_digest":"5355cff72783e30f96e3e47aef440b0408a7bf550e53a00c8df139186f37ea25","base_imm32_sha256":"989c1e1d2358ae47b3fe700631551a1b4563e4b2db738d26060c97a37f11aedf","base_winex11_sha256":"5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5","imm32_sha256":"6ffb4ef5528e48d6e79d7d9da0fe7d0d86f2cfa3ece0847f886942583f28a5aa","input_patch_sha256":"fbd10d91030ee42aea469d01fc123fb2f3fe6defabb982960b1754933fb26448","schema":1,"source_commit":"4b12965ca7e78b8e45eee5f835c72963b3ce351d","winex11_sha256":"846f33382d663be8e4d92d0c533044c4b89f4c5c44a347fbf007221b12024bd8"}' \
  > "$staged_runtime/.msclassic-input-diagnostic.json"
chmod 0600 "$staged_runtime/.msclassic-input-diagnostic.json"
mv "$staged_runtime" "$output_runtime"
staged_runtime=""
printf 'Contextual-input Wine runtime created: %s\n' "$output_runtime"
