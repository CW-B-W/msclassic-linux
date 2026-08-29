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
expected_patch_sha="cc4f9c670b2ba82955862f7997539809dd087a8b34cd1d02636176b5217454a8"
expected_base_winex11_sha="5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5"
expected_base_ntdll_sha="2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d"
expected_winex11_sha="6153c26e860a46c2fdf4944f3c4309453649bf0cf75df79d899f248973c130ce"
expected_winex11_size="545568"
source_dir="$build_cache/wine-tkg-inputdiag-11.10"
build_dir="$build_cache/wine-tkg-inputdiag-build-11.10-v1"
base_winex11="$base_runtime/lib/wine/x86_64-unix/winex11.so"
base_ntdll="$base_runtime/lib/wine/x86_64-windows/ntdll.dll"
built_winex11="$build_dir/dlls/winex11.drv/winex11.so"

for command in git make gcc g++ bison flex strip sha256sum; do
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
staged_runtime=""
cleanup() {
  if [[ "${patch_applied:-0}" == 1 ]]; then
    git -C "$source_dir" apply --reverse "$patch_file" >/dev/null 2>&1 || true
  fi
  [[ -z "$staged_winex11" || ! -e "$staged_winex11" ]] || rm -f "$staged_winex11"
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
make -C "$build_dir" -j"$(getconf _NPROCESSORS_ONLN)" dlls/winex11.drv/winex11.so

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

output_parent="$(dirname "$output_runtime")"
mkdir -p -m 700 "$output_parent"
staged_runtime="$(mktemp -d "$output_parent/.wine-inputdiag-runtime-XXXXXX")"
cp -a --reflink=auto "$base_runtime/." "$staged_runtime/"
install -m 0644 "$staged_winex11" "$staged_runtime/lib/wine/x86_64-unix/winex11.so"
printf '%s\n' \
  '{"base_digest":"5355cff72783e30f96e3e47aef440b0408a7bf550e53a00c8df139186f37ea25","base_winex11_sha256":"5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5","input_patch_sha256":"cc4f9c670b2ba82955862f7997539809dd087a8b34cd1d02636176b5217454a8","schema":1,"source_commit":"4b12965ca7e78b8e45eee5f835c72963b3ce351d","winex11_sha256":"6153c26e860a46c2fdf4944f3c4309453649bf0cf75df79d899f248973c130ce"}' \
  > "$staged_runtime/.msclassic-input-diagnostic.json"
chmod 0600 "$staged_runtime/.msclassic-input-diagnostic.json"
mv "$staged_runtime" "$output_runtime"
staged_runtime=""
printf 'Input diagnostic Wine runtime created: %s\n' "$output_runtime"
