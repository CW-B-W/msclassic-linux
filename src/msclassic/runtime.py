from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .lockfile import Artifact
from .paths import AppPaths


PATCH_ID = "wine-11.10-ntdll-frame-walk-page-fault-guard-v1"
SOURCE_COMMIT = "4b12965ca7e78b8e45eee5f835c72963b3ce351d"
PATCHED_BUILD_HOME = Path("/home/ubuntu")
PATCHED_BUILD_CACHE = PATCHED_BUILD_HOME / ".cache/msclassic-build"
PATCHED_RUNTIME_SUFFIX = "-msclassic1"
DIAGNOSTIC_RUNTIME_SUFFIX = "-msclassic-inputdiag1"
PATCHED_NTDLL_SHA256 = "2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d"
PATCHED_NTDLL_SIZE = 1_101_568
PATCH_STAMP = ".msclassic-runtime.json"
NTDLL_RELATIVE = Path("lib/wine/x86_64-windows/ntdll.dll")
DIAGNOSTIC_STAMP = ".msclassic-input-diagnostic.json"
DIAGNOSTIC_WINEX11_RELATIVE = Path("lib/wine/x86_64-unix/winex11.so")
DIAGNOSTIC_BASE_WINEX11_SHA256 = "5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5"
DIAGNOSTIC_PATCH_SHA256 = "cc4f9c670b2ba82955862f7997539809dd087a8b34cd1d02636176b5217454a8"
DIAGNOSTIC_WINEX11_SHA256 = "6153c26e860a46c2fdf4944f3c4309453649bf0cf75df79d899f248973c130ce"
DIAGNOSTIC_WINEX11_SIZE = 545_568


def patched_runtime_root(paths: AppPaths, artifact: Artifact) -> Path:
    return paths.tools / f"{artifact.version}{PATCHED_RUNTIME_SUFFIX}"


def diagnostic_runtime_root(paths: AppPaths, artifact: Artifact) -> Path:
    return paths.tools / f"{artifact.version}{DIAGNOSTIC_RUNTIME_SUFFIX}"


def patched_runtime_build_supported(paths: AppPaths) -> bool:
    try:
        return paths.home.resolve() == PATCHED_BUILD_HOME
    except OSError:
        return False


def patched_runtime_manifest(artifact: Artifact) -> dict[str, object]:
    return {
        "schema": 1,
        "base_digest": artifact.digest,
        "ntdll_sha256": PATCHED_NTDLL_SHA256,
        "patch": PATCH_ID,
        "source_commit": SOURCE_COMMIT,
    }


def diagnostic_runtime_manifest(artifact: Artifact) -> dict[str, object]:
    return {
        "schema": 1,
        "base_digest": artifact.digest,
        "source_commit": SOURCE_COMMIT,
        "base_winex11_sha256": DIAGNOSTIC_BASE_WINEX11_SHA256,
        "input_patch_sha256": DIAGNOSTIC_PATCH_SHA256,
        "winex11_sha256": DIAGNOSTIC_WINEX11_SHA256,
    }


def patched_runtime_valid(paths: AppPaths, artifact: Artifact) -> bool:
    tools = paths.tools.resolve()
    root = patched_runtime_root(paths, artifact).resolve()
    if not root.is_relative_to(tools):
        return False
    return _patched_runtime_content_valid(root, artifact)


def diagnostic_runtime_valid(paths: AppPaths, artifact: Artifact) -> bool:
    tools = paths.tools.resolve()
    root = diagnostic_runtime_root(paths, artifact).resolve()
    if not root.is_relative_to(tools) or not _patched_runtime_content_valid(root, artifact):
        return False
    if not _json_matches(root / DIAGNOSTIC_STAMP, diagnostic_runtime_manifest(artifact)):
        return False
    driver = root / DIAGNOSTIC_WINEX11_RELATIVE
    try:
        if driver.stat().st_size != DIAGNOSTIC_WINEX11_SIZE:
            return False
        with driver.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == DIAGNOSTIC_WINEX11_SHA256
    except OSError:
        return False


def _patched_runtime_content_valid(root: Path, artifact: Artifact) -> bool:
    wine = root / "bin/wine"
    wineserver = root / "bin/wineserver"
    if not (
        wine.is_file()
        and os.access(wine, os.X_OK)
        and wineserver.is_file()
        and os.access(wineserver, os.X_OK)
    ):
        return False
    if not _json_matches(
        root / ".msclassic-artifact.json",
        {
            "schema": 1,
            "name": artifact.name,
            "version": artifact.version,
            "digest": artifact.digest,
        },
    ):
        return False
    if not _json_matches(root / PATCH_STAMP, patched_runtime_manifest(artifact)):
        return False
    ntdll = root / NTDLL_RELATIVE
    try:
        if ntdll.stat().st_size != PATCHED_NTDLL_SIZE:
            return False
        with ntdll.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == PATCHED_NTDLL_SHA256
    except OSError:
        return False


def _json_matches(path: Path, expected: dict[str, object]) -> bool:
    try:
        if path.stat().st_size > 4096:
            return False
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return actual == expected
