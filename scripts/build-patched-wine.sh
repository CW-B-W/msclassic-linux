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
  printf 'ERROR: patched Wine v1 requires build cache %s.\n' "$required_build_cache" >&2
  exit 1
}

source_url="https://github.com/Kron4ek/wine-tkg.git"
source_commit="4b12965ca7e78b8e45eee5f835c72963b3ce351d"
source_epoch="1787832121"
patch_file="$project_root/patches/wine-11.10-ntdll-frame-walk-page-fault-guard.patch"
expected_patch_sha="0a438e21f7d12ea337b9119c7cc2f48f99e2bf6fe38abc00070d9aa46a03ca06"
expected_source_sha="d9e552cde6906fea3089027aec73d4c5088f1b97f145afe470dd60f54cd032af"
expected_base_ntdll_sha="d1174ee9880239c5e5827eb9a43d50907fc7495c6171b8eb5d8db9dbb4135398"
expected_ntdll_sha="2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d"
# Wine embeds absolute source paths in ntdll.dll. Keep the v1 paths identical
# to the runtime that passed the Lubuntu 24.04 launch test. The installer uses
# ~/.cache/msclassic-build, so identically provisioned `ubuntu` VM clones get
# byte-for-byte identical output. A path-independent v2 build is tracked as a
# portability follow-up rather than silently accepting an unverified binary.
source_dir="$build_cache/wine-tkg-11.10"
build_dir="$build_cache/wine-tkg-build-11.10"
base_ntdll="$base_runtime/lib/wine/x86_64-windows/ntdll.dll"
built_ntdll="$build_dir/dlls/ntdll/x86_64-windows/ntdll.dll"

for command in git make gcc bison flex x86_64-w64-mingw32-gcc x86_64-w64-mingw32-strip sha256sum; do
  command -v "$command" >/dev/null || {
    printf 'ERROR: missing patched-Wine build command: %s\n' "$command" >&2
    exit 1
  }
done

[[ -d "$base_runtime" && -x "$base_runtime/bin/wine" && -x "$base_runtime/bin/wineserver" ]] || {
  printf 'ERROR: locked base Wine runtime is unavailable.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_base_ntdll_sha" "$base_ntdll" | sha256sum --check --status || {
  printf 'ERROR: locked base Wine NTDLL does not match the expected input.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_patch_sha" "$patch_file" | sha256sum --check --status || {
  printf 'ERROR: Wine source patch failed verification.\n' >&2
  exit 1
}

if [[ -e "$output_runtime" ]]; then
  printf 'ERROR: patched Wine output already exists; refusing to overwrite it.\n' >&2
  exit 1
fi

mkdir -p -m 700 "$build_cache"
if [[ ! -d "$source_dir/.git" ]]; then
  clone_dir="$(mktemp -d "$build_cache/.wine-source-XXXXXX")"
  trap 'rm -rf "$clone_dir"' EXIT
  git -C "$clone_dir" init --quiet
  git -C "$clone_dir" remote add origin "$source_url"
  git -C "$clone_dir" fetch --quiet --depth=1 origin "$source_commit"
  git -C "$clone_dir" checkout --quiet --detach FETCH_HEAD
  git -C "$clone_dir" apply "$patch_file"
  mv "$clone_dir" "$source_dir"
  trap - EXIT
fi

[[ "$(git -C "$source_dir" rev-parse HEAD)" == "$source_commit" ]] || {
  printf 'ERROR: cached Wine source commit is invalid.\n' >&2
  exit 1
}
printf '%s  %s\n' "$expected_source_sha" "$source_dir/dlls/ntdll/signal_x86_64.c" | sha256sum --check --status || {
  printf 'ERROR: cached patched Wine source is invalid.\n' >&2
  exit 1
}

mkdir -p -m 700 "$build_dir"
if [[ ! -f "$build_dir/Makefile" ]]; then
  (
    cd "$build_dir"
    "$source_dir/configure" \
      --enable-win64 \
      --without-x \
      --without-wayland \
      --without-freetype \
      --without-gnutls
  )
fi
make -C "$build_dir" -j"$(getconf _NPROCESSORS_ONLN)" dlls/ntdll/x86_64-windows/ntdll.dll

staged_ntdll="$(mktemp "$build_cache/.ntdll-XXXXXX.dll")"
trap 'rm -f "$staged_ntdll"' EXIT
cp "$built_ntdll" "$staged_ntdll"
SOURCE_DATE_EPOCH="$source_epoch" x86_64-w64-mingw32-strip --strip-debug "$staged_ntdll"
printf '%s  %s\n' "$expected_ntdll_sha" "$staged_ntdll" | sha256sum --check --status || {
  printf 'ERROR: patched NTDLL build is not reproducible on this toolchain.\n' >&2
  exit 1
}

output_parent="$(dirname "$output_runtime")"
mkdir -p -m 700 "$output_parent"
staged_runtime="$(mktemp -d "$output_parent/.wine-runtime-XXXXXX")"
trap 'rm -f "$staged_ntdll"; rm -rf "$staged_runtime"' EXIT
cp -a --reflink=auto "$base_runtime/." "$staged_runtime/"
install -m 0644 "$staged_ntdll" "$staged_runtime/lib/wine/x86_64-windows/ntdll.dll"
printf '%s\n' \
  '{"base_digest":"5355cff72783e30f96e3e47aef440b0408a7bf550e53a00c8df139186f37ea25","ntdll_sha256":"2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d","patch":"wine-11.10-ntdll-frame-walk-page-fault-guard-v1","schema":1,"source_commit":"4b12965ca7e78b8e45eee5f835c72963b3ce351d"}' \
  > "$staged_runtime/.msclassic-runtime.json"
chmod 0600 "$staged_runtime/.msclassic-runtime.json"
mv "$staged_runtime" "$output_runtime"
rm -f "$staged_ntdll"
trap - EXIT
printf 'Patched Wine runtime created: %s\n' "$output_runtime"
