from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .lockfile import Artifact, load_versions, verify_file
from .paths import AppPaths
from .runtime import patched_runtime_root, patched_runtime_valid


UPDATE_HEADROOM_BYTES = 1024**3
MAX_UPDATE_BYTES = 256 * 1024**3
_REPO = Path(__file__).resolve().parents[2]


class UpdaterError(ValueError):
    pass


@dataclass(frozen=True)
class UpdateCheck:
    total_size: int
    available: int
    allowed: bool
    reason: str


def parse_update_json(output: str) -> int:
    if not isinstance(output, str) or len(output.encode("utf-8")) > 1024 * 1024:
        raise UpdaterError("nxdl check output is invalid")
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise UpdaterError("nxdl check output is not one JSON object") from exc
    if not isinstance(value, dict):
        raise UpdaterError("nxdl check output is not an object")
    total_size = value.get("total_size")
    if (
        not isinstance(total_size, int)
        or isinstance(total_size, bool)
        or total_size < 0
        or total_size > MAX_UPDATE_BYTES
    ):
        raise UpdaterError("nxdl reported an invalid update size")
    return total_size


def check_update(paths: AppPaths, nxdl: Artifact) -> UpdateCheck:
    _ensure_not_locked(paths)
    return _check_without_lock(paths, nxdl)


def apply_update(paths: AppPaths, nxdl: Artifact) -> int:
    with _exclusive_launch_lock(paths):
        check = _check_without_lock(paths, nxdl)
        if not check.allowed:
            raise UpdaterError(check.reason)
        binary = _verified_nxdl(paths, nxdl)
        try:
            completed = subprocess.run(
                [str(binary), "tms_cw", "--download", str(paths.client)],
                shell=False,
                env=_minimal_environment(paths),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60 * 60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdaterError("nxdl download failed") from exc
        return completed.returncode


def stop_prefix(paths: AppPaths, confirmed: bool) -> int:
    if not confirmed:
        raise UpdaterError("prefix stop requires explicit confirmation")
    artifact = load_versions(_REPO / "versions.lock")["wine"]
    tools = paths.tools.resolve()
    wine_root = patched_runtime_root(paths, artifact).resolve()
    wineserver = (wine_root / "bin/wineserver").resolve()
    if (
        not wine_root.is_relative_to(tools)
        or not wineserver.is_relative_to(wine_root)
        or not patched_runtime_valid(paths, artifact)
        or not wineserver.is_file()
        or not os.access(wineserver, os.X_OK)
    ):
        raise UpdaterError("pinned prefix wineserver is unavailable")
    environment = {
        "HOME": str(paths.home),
        "PATH": f"{wine_root / 'bin'}:/usr/bin:/bin",
        "WINEPREFIX": str(paths.prefix),
    }
    try:
        killed = subprocess.run(
            [str(wineserver), "-k"],
            shell=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        if killed.returncode != 0:
            return killed.returncode
        waited = subprocess.run(
            [str(wineserver), "-w"],
            shell=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdaterError("dedicated prefix did not stop cleanly") from exc
    return waited.returncode


def _check_without_lock(paths: AppPaths, nxdl: Artifact) -> UpdateCheck:
    binary = _verified_nxdl(paths, nxdl)
    if not paths.client.is_dir() or not os.access(paths.client, os.W_OK):
        raise UpdaterError("writable client directory is required")
    try:
        completed = subprocess.run(
            [str(binary), "tms_cw", "--check", "--json"],
            shell=False,
            env=_minimal_environment(paths),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdaterError("nxdl check failed") from exc
    if completed.returncode != 0:
        raise UpdaterError("nxdl check returned a failure")
    total_size = parse_update_json(completed.stdout)
    try:
        available = shutil.disk_usage(paths.client.parent).free
    except OSError as exc:
        raise UpdaterError("cannot inspect client free space") from exc
    needed = total_size + UPDATE_HEADROOM_BYTES
    allowed = available >= needed
    reason = "ready" if allowed else "insufficient disk space for update plus 1 GiB headroom"
    return UpdateCheck(total_size, available, allowed, reason)


def _verified_nxdl(paths: AppPaths, artifact: Artifact) -> Path:
    if artifact.name != "nxdl":
        raise UpdaterError("nxdl artifact metadata is required")
    tools = paths.tools.resolve()
    binary = (paths.tools / f"nxdl-{artifact.version}" / "nxdl").resolve()
    if not binary.is_relative_to(tools) or not verify_file(binary, artifact):
        raise UpdaterError("nxdl checksum verification failed")
    if not os.access(binary, os.X_OK):
        raise UpdaterError("verified nxdl binary is not executable")
    return binary


def _ensure_not_locked(paths: AppPaths) -> None:
    lock_path = paths.state / "launch.lock"
    if not lock_path.exists():
        return
    try:
        with lock_path.open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
    except (BlockingIOError, OSError) as exc:
        raise UpdaterError("game launch or update is active") from exc


@contextlib.contextmanager
def _exclusive_launch_lock(paths: AppPaths) -> Iterator[None]:
    paths.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = paths.state / "launch.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdaterError("game launch or update is active") from exc
        yield


def _minimal_environment(paths: AppPaths) -> dict[str, str]:
    environment = {
        "HOME": str(paths.home),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    for key in ("HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"):
        if key in os.environ:
            environment[key] = os.environ[key]
    return environment
