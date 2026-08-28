from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from .lockfile import Artifact, verify_file
from .paths import AppPaths


DOWNLOAD_HEADROOM_BYTES = 1024**3
MAX_DOWNLOAD_BYTES = 256 * 1024**3
MAX_MANIFEST_OUTPUT_BYTES = 1024 * 1024


class ClientDownloadError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadCheck:
    total_size: int
    available: int
    allowed: bool
    reason: str


def parse_download_json(output: str) -> int:
    if not isinstance(output, str) or len(output.encode("utf-8")) > MAX_MANIFEST_OUTPUT_BYTES:
        raise ClientDownloadError("nxdl check output is invalid")
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ClientDownloadError("nxdl check output is not one JSON object") from exc
    if not isinstance(value, dict):
        raise ClientDownloadError("nxdl check output is not an object")
    total_size = value.get("total_size")
    if (
        not isinstance(total_size, int)
        or isinstance(total_size, bool)
        or total_size < 0
        or total_size > MAX_DOWNLOAD_BYTES
    ):
        raise ClientDownloadError("nxdl reported an invalid download size")
    return total_size


def check_download(paths: AppPaths, nxdl: Artifact) -> DownloadCheck:
    _ensure_not_locked(paths)
    return _check_without_lock(paths, nxdl)


def download_and_promote(
    paths: AppPaths,
    nxdl: Artifact,
    validate_client: Callable[[Path], None],
) -> None:
    games = _games_directory(paths)
    stage = paths.client.with_name(".MapleStoryClassic.download")
    _require_managed_client_paths(paths, games, stage)
    with _exclusive_launch_lock(paths):
        if _path_exists(paths.client):
            _validate_existing_client(paths.client, validate_client)
            return
        check = _check_without_lock(paths, nxdl)
        if not check.allowed:
            raise ClientDownloadError(check.reason)
        _ensure_games_directory(games)
        if _path_exists(stage):
            _reject_unsafe_tree(stage)
        _run_nxdl_download(_verified_nxdl(paths, nxdl), paths, stage)
        _reject_unsafe_tree(stage)
        normalize_windows_backslash_names(stage)
        _reject_unsafe_tree(stage)
        _validate_downloaded_client(stage, validate_client)
        if _path_exists(paths.client):
            raise ClientDownloadError("client destination appeared during download")
        try:
            stage.replace(paths.client)
        except OSError as exc:
            raise ClientDownloadError("client promotion failed") from exc
        _validate_existing_client(paths.client, validate_client)


def normalize_windows_backslash_names(staging: Path) -> None:
    _reject_unsafe_tree(staging)
    moves: list[tuple[Path, Path]] = []
    for directory, directories, filenames in os.walk(staging, topdown=True, followlinks=False):
        if any("\\" in name for name in directories):
            raise ClientDownloadError("download contains an unsafe Windows-style directory")
        base = Path(directory)
        for filename in filenames:
            if "\\" not in filename:
                continue
            components = filename.split("\\")
            if any(
                not component
                or component in {".", ".."}
                or "/" in component
                for component in components
            ):
                raise ClientDownloadError("download contains an unsafe Windows-style filename")
            source = base / filename
            destination = base.joinpath(*components)
            try:
                destination.relative_to(staging)
            except ValueError as exc:
                raise ClientDownloadError("download filename escapes staging") from exc
            moves.append((source, destination))

    destinations = [destination for _, destination in moves]
    if len(set(destinations)) != len(destinations):
        raise ClientDownloadError("download filename normalization collides")
    for source, destination in moves:
        if _path_exists(destination):
            raise ClientDownloadError("download filename normalization collides")
        _validate_destination_parents(staging, destination.parent)
        if not source.is_file() or source.is_symlink():
            raise ClientDownloadError("download contains an unsafe Windows-style file")
    for source, destination in moves:
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        try:
            source.replace(destination)
        except OSError as exc:
            raise ClientDownloadError("download filename normalization failed") from exc


def _check_without_lock(paths: AppPaths, nxdl: Artifact) -> DownloadCheck:
    binary = _verified_nxdl(paths, nxdl)
    try:
        completed = subprocess.run(
            [str(binary), "tms_cw", "--check", "--json"],
            shell=False,
            env=_minimal_environment(paths),
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientDownloadError("nxdl check failed") from exc
    if completed.returncode != 0:
        raise ClientDownloadError("nxdl check returned a failure")
    total_size = parse_download_json(completed.stdout)
    games = _games_directory(paths)
    try:
        available = shutil.disk_usage(games if games.is_dir() else paths.home).free
    except OSError as exc:
        raise ClientDownloadError("cannot inspect client free space") from exc
    needed = total_size + DOWNLOAD_HEADROOM_BYTES
    allowed = available >= needed
    return DownloadCheck(
        total_size,
        available,
        allowed,
        "ready" if allowed else "insufficient disk space for download plus 1 GiB headroom",
    )


def _run_nxdl_download(binary: Path, paths: AppPaths, stage: Path) -> None:
    try:
        completed = subprocess.run(
            [str(binary), "tms_cw", "--download", str(stage)],
            shell=False,
            env=_minimal_environment(paths),
            stdin=subprocess.DEVNULL,
            timeout=6 * 60 * 60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClientDownloadError("nxdl download failed") from exc
    if completed.returncode != 0:
        raise ClientDownloadError("nxdl download failed")


def _verified_nxdl(paths: AppPaths, artifact: Artifact) -> Path:
    if artifact.name != "nxdl":
        raise ClientDownloadError("nxdl artifact metadata is required")
    tools = paths.tools.resolve()
    binary = (paths.tools / f"nxdl-{artifact.version}" / "nxdl").resolve()
    if not binary.is_relative_to(tools) or not verify_file(binary, artifact):
        raise ClientDownloadError("nxdl checksum verification failed")
    if not os.access(binary, os.X_OK):
        raise ClientDownloadError("verified nxdl binary is not executable")
    return binary


def _games_directory(paths: AppPaths) -> Path:
    games = paths.home / "Games"
    if paths.client.parent != games or paths.client.name != "MapleStoryClassic":
        raise ClientDownloadError("client destination is not managed")
    if _path_exists(games):
        _require_directory(games, "Games directory")
    elif not paths.home.is_dir():
        raise ClientDownloadError("home directory is unavailable")
    return games


def _require_managed_client_paths(paths: AppPaths, games: Path, stage: Path) -> None:
    if stage.parent != games or stage.name != ".MapleStoryClassic.download":
        raise ClientDownloadError("client staging destination is not managed")
    try:
        games.resolve().relative_to(paths.home.resolve())
    except (OSError, ValueError) as exc:
        raise ClientDownloadError("client destination escapes home") from exc


def _ensure_games_directory(games: Path) -> None:
    if _path_exists(games):
        _require_directory(games, "Games directory")
        return
    try:
        games.mkdir(mode=0o755, parents=True, exist_ok=False)
    except OSError as exc:
        raise ClientDownloadError("cannot create Games directory") from exc


def _validate_existing_client(client: Path, validate_client: Callable[[Path], None]) -> None:
    _reject_unsafe_tree(client)
    try:
        validate_client(client)
    except (OSError, ValueError) as exc:
        raise ClientDownloadError("existing client is invalid; refusing to replace it") from exc


def _validate_downloaded_client(stage: Path, validate_client: Callable[[Path], None]) -> None:
    try:
        validate_client(stage)
    except (OSError, ValueError) as exc:
        raise ClientDownloadError("downloaded client is incomplete") from exc


def _reject_unsafe_tree(root: Path) -> None:
    _require_directory(root, "client staging directory")
    for directory, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(directory)
        _require_directory(base, "client tree")
        for name in (*directories, *filenames):
            candidate = base / name
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                raise ClientDownloadError("cannot inspect downloaded client") from exc
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ClientDownloadError("downloaded client contains a link or special file")


def _validate_destination_parents(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ClientDownloadError("download filename escapes staging") from exc
    current = root
    for component in relative.parts:
        current = current / component
        if _path_exists(current):
            _require_directory(current, "download destination parent")


def _require_directory(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise ClientDownloadError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ClientDownloadError(f"{label} is unsafe")


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ClientDownloadError("cannot inspect client path") from exc
    return True


def _ensure_not_locked(paths: AppPaths) -> None:
    lock_path = paths.state / "launch.lock"
    if not lock_path.exists():
        return
    try:
        with lock_path.open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
    except (BlockingIOError, OSError) as exc:
        raise ClientDownloadError("game launch or update is active") from exc


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
            raise ClientDownloadError("game launch or update is active") from exc
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
