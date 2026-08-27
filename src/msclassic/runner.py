from __future__ import annotations

import fcntl
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .approval import ensure_current_boot_approval
from .doctor import collect_graphics_report
from .lockfile import load_versions
from .paths import AppPaths
from .protocol import LaunchRequest
from .redaction import assert_export_safe


class RunnerError(ValueError):
    pass


class ActiveSessionError(RunnerError):
    pass


@dataclass(frozen=True)
class HandlerInstallResult:
    previous: dict[str, str]
    current: str
    desktop_file: Path


_PASSTHROUGH_ENV = (
    "DISPLAY",
    "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "PULSE_SERVER",
    "PIPEWIRE_REMOTE",
)
_DESKTOP_NAME = "msclassic-ngm.desktop"
_LEGACY_DESKTOP_NAMES = {"maplestory-classic-nexonplug.desktop"}
_SCHEMES = (
    "x-scheme-handler/nexonplug",
    "x-scheme-handler/NexonPlug",
    "x-scheme-handler/ngm",
)
_REPO = Path(__file__).resolve().parents[2]


def build_wine_command(
    request: LaunchRequest,
    paths: AppPaths,
) -> tuple[dict[str, str], tuple[str, ...]]:
    artifact = load_versions(_REPO / "versions.lock")["wine"]
    wine_root = paths.tools / artifact.version
    wine = wine_root / "bin/wine"
    executable = paths.client / "Maplestory_Classic.exe"
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
    argv = (str(wine), str(executable), *request.arguments)
    return environment, argv


def run_authenticated(
    request: LaunchRequest,
    paths: AppPaths,
    *,
    collector=collect_graphics_report,
) -> int:
    paths.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = paths.state / "launch.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ActiveSessionError("a MapleStory Classic launch is already active") from exc
        ensure_current_boot_approval(paths, collector)
        _validate_runtime(paths)
        environment, argv = build_wine_command(request, paths)
        _write_launch_status(paths, "starting")
        try:
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
        except OSError:
            _write_launch_status(paths, "spawn-failed")
            raise
        _write_launch_status(paths, "exited", completed.returncode)
        return completed.returncode


def _write_launch_status(paths: AppPaths, stage: str, exit_code: int | None = None) -> None:
    if stage not in {"starting", "spawn-failed", "exited"}:
        raise RunnerError("invalid launch status")
    payload: dict[str, object] = {"schema": 1, "stage": stage}
    if exit_code is not None:
        payload["exit_code"] = int(exit_code)
    assert_export_safe(payload)
    path = paths.state / "last-launch-status.json"
    temporary = path.with_suffix(".json.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def install_desktop_handler(paths: AppPaths) -> HandlerInstallResult:
    applications = paths.data.parent / "applications"
    desktop_file = applications / _DESKTOP_NAME
    rollback_file = paths.config / "handler-rollback.json"
    wrapper = paths.home / ".local/bin/msclassic"
    if any(character.isspace() for character in str(wrapper)) or any(
        character in str(wrapper) for character in ('"', "'", "\\")
    ):
        raise RunnerError("desktop wrapper path contains unsupported characters")

    discovered = {scheme: _query_handler(scheme) for scheme in _SCHEMES}
    if rollback_file.exists():
        rollback = _read_rollback(rollback_file)
        if rollback["schema"] == 1:
            previous = dict(discovered)
            previous[_SCHEMES[0]] = str(rollback["previous"])
            rollback = {"schema": 2, "previous": previous, "current": _DESKTOP_NAME}
            _write_rollback(rollback_file, rollback)
        else:
            previous = dict(rollback["previous"])
            if rollback["current"] != _DESKTOP_NAME:
                _write_rollback(
                    rollback_file,
                    {"schema": 2, "previous": previous, "current": _DESKTOP_NAME},
                )
    else:
        previous = discovered

    template = Path(__file__).resolve().parents[2] / "desktop/msclassic-ngm.desktop.in"
    try:
        rendered = template.read_text(encoding="utf-8").replace("@WRAPPER@", str(wrapper))
    except OSError as exc:
        raise RunnerError("desktop handler template is unavailable") from exc
    if "@WRAPPER@" in rendered:
        raise RunnerError("desktop handler template was not fully rendered")

    applications.mkdir(mode=0o755, parents=True, exist_ok=True)
    paths.config.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = desktop_file.with_suffix(".desktop.tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(desktop_file)

    if not rollback_file.exists():
        rollback = {"schema": 2, "previous": previous, "current": _DESKTOP_NAME}
        _write_rollback(rollback_file, rollback)

    _desktop_command(["update-desktop-database", str(applications)])
    for scheme in _SCHEMES:
        _desktop_command(["xdg-mime", "default", _DESKTOP_NAME, scheme])
        if _query_handler(scheme) != _DESKTOP_NAME:
            raise RunnerError("web launcher desktop handler verification failed")
    return HandlerInstallResult(previous, _DESKTOP_NAME, desktop_file)


def restore_desktop_handler(paths: AppPaths) -> None:
    applications = paths.data.parent / "applications"
    desktop_file = applications / _DESKTOP_NAME
    rollback_file = paths.config / "handler-rollback.json"
    rollback = _read_rollback(rollback_file)
    if rollback["schema"] == 1:
        previous = {_SCHEMES[0]: str(rollback["previous"])}
    else:
        previous = dict(rollback["previous"])
    for scheme, desktop_name in previous.items():
        if desktop_name:
            _desktop_command(["xdg-mime", "default", desktop_name, scheme])
            if _query_handler(scheme) != desktop_name:
                raise RunnerError("previous web launcher handler restoration failed")
    try:
        desktop_file.unlink(missing_ok=True)
        rollback_file.unlink()
    except OSError as exc:
        raise RunnerError("cannot remove desktop handler state") from exc
    _desktop_command(["update-desktop-database", str(applications)])


def _validate_runtime(paths: AppPaths) -> None:
    artifact = load_versions(_REPO / "versions.lock")["wine"]
    tools = paths.tools.resolve()
    wine_root = (paths.tools / artifact.version).resolve()
    wine = wine_root / "bin/wine"
    wineserver = wine_root / "bin/wineserver"
    executable = paths.client / "Maplestory_Classic.exe"
    if not wine_root.is_relative_to(tools):
        raise RunnerError("pinned Wine runtime path is invalid")
    if not wine.is_file() or not os.access(wine, os.X_OK):
        raise RunnerError("pinned Wine launcher is unavailable")
    if not wineserver.is_file() or not os.access(wineserver, os.X_OK):
        raise RunnerError("pinned Wine server is unavailable")
    artifact_stamp = wine_root / ".msclassic-artifact.json"
    try:
        if artifact_stamp.stat().st_size > 4096:
            raise RunnerError("Wine artifact stamp is invalid")
        installed_artifact = json.loads(artifact_stamp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError("Wine artifact stamp is unavailable") from exc
    if installed_artifact != {
        "schema": 1,
        "name": artifact.name,
        "version": artifact.version,
        "digest": artifact.digest,
    }:
        raise RunnerError("Wine runtime does not match the locked artifact")
    if not executable.is_file() or not os.access(executable, os.R_OK | os.W_OK):
        raise RunnerError("writable MapleStory Classic executable is unavailable")


def _query_handler(scheme: str) -> str:
    result = _desktop_command(["xdg-mime", "query", "default", scheme], allow_empty=True)
    return result.stdout.strip()


def _desktop_command(argv: list[str], *, allow_empty: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            shell=False,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RunnerError("desktop integration command is unavailable") from exc
    if result.returncode != 0 or (not allow_empty and argv[0] == "xdg-mime" and not argv[1] == "default"):
        raise RunnerError("desktop integration command failed")
    return result


def _read_rollback(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 4096:
            raise RunnerError("desktop rollback state is invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerError("desktop rollback state is unavailable") from exc
    if not isinstance(value, dict) or set(value) != {"schema", "previous", "current"}:
        raise RunnerError("desktop rollback state is invalid")
    if value.get("current") not in {_DESKTOP_NAME, *_LEGACY_DESKTOP_NAMES}:
        raise RunnerError("desktop rollback state is invalid")
    if value.get("schema") == 1:
        previous = value.get("previous")
        if not isinstance(previous, str) or "/" in previous:
            raise RunnerError("desktop rollback state is invalid")
        return value
    if value.get("schema") != 2:
        raise RunnerError("desktop rollback state is invalid")
    previous = value.get("previous")
    if (
        not isinstance(previous, dict)
        or set(previous) != set(_SCHEMES)
        or any(not isinstance(item, str) or "/" in item for item in previous.values())
    ):
        raise RunnerError("desktop rollback state is invalid")
    return value


def _write_rollback(path: Path, rollback: dict[str, object]) -> None:
    assert_export_safe(rollback)
    path.write_text(json.dumps(rollback, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
