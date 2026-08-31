"""Optional debugger launcher for authorized compatibility testing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .lockfile import load_versions
from .paths import AppPaths
from .runtime import patched_runtime_root, patched_runtime_valid


_PASSTHROUGH_ENV = (
    "DISPLAY",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "PULSE_SERVER",
    "PIPEWIRE_REMOTE",
)
_REPO = Path(__file__).resolve().parents[2]


class DebuggerError(ValueError):
    pass


def build_windows_ce_command(
    executable: Path,
    paths: AppPaths,
) -> tuple[dict[str, str], tuple[str, ...]]:
    artifact = load_versions(_REPO / "versions.lock")["wine"]
    wine_root = patched_runtime_root(paths, artifact)
    environment = {
        key: os.environ[key]
        for key in _PASSTHROUGH_ENV
        if key in os.environ and os.environ[key]
    }
    environment.update(
        {
            "HOME": str(paths.home),
            "PATH": f"{wine_root / 'bin'}:/usr/bin:/bin",
            "WINEPREFIX": str(paths.prefix),
            "WINEDEBUG": "-all",
            "LANG": "zh_TW.UTF-8",
            "LC_ALL": "zh_TW.UTF-8",
        }
    )
    return environment, (str(wine_root / "bin/wine"), str(executable))


def run_windows_ce(executable: Path, paths: AppPaths) -> int:
    if executable.suffix.lower() != ".exe":
        raise DebuggerError("select a Windows Cheat Engine executable (.exe)")
    try:
        executable = executable.expanduser().resolve(strict=True)
    except OSError as exc:
        raise DebuggerError("Windows Cheat Engine executable is unavailable") from exc
    if not executable.is_file() or not os.access(executable, os.R_OK):
        raise DebuggerError("Windows Cheat Engine executable is unavailable")
    if not paths.prefix.is_dir():
        raise DebuggerError("MapleStory Classic Wine prefix is unavailable")

    artifact = load_versions(_REPO / "versions.lock")["wine"]
    if not patched_runtime_valid(paths, artifact):
        raise DebuggerError("Wine runtime does not match the locked patched profile")

    environment, argv = build_windows_ce_command(executable, paths)
    completed = subprocess.run(
        list(argv),
        shell=False,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        check=False,
    )
    return completed.returncode
