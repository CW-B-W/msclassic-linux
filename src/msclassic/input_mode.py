from __future__ import annotations

import base64
import configparser
import io
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree

from .paths import AppPaths


class InputModeError(ValueError):
    pass


@dataclass(frozen=True)
class InputModeStatus:
    state: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"state": self.state, "detail": self.detail}


@dataclass(frozen=True)
class DesktopPaths:
    openbox: Path
    lxqt: Path
    system_openbox: Path
    system_lxqt: Path
    transaction: Path


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    content: bytes
    mode: int


SYSTEM_OPENBOX = Path("/etc/xdg/openbox/rc.xml")
SYSTEM_LXQT = Path("/etc/xdg/lxqt/globalkeyshortcuts.conf/globalkeyshortcuts.conf")
_LXQT_SERVICE = "app-lxqt\\x2dglobalkeyshortcuts@autostart.service"


def deactivate_fcitx(environment: Mapping[str, str]) -> InputModeStatus:
    command = shutil.which("fcitx5-remote")
    if not command or not environment.get("DBUS_SESSION_BUS_ADDRESS"):
        return InputModeStatus("unavailable", "Fcitx is unavailable")
    try:
        result = subprocess.run(
            [command, "-c"],
            shell=False,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return InputModeStatus("unavailable", "Fcitx is unavailable")
    if result.returncode != 0:
        return InputModeStatus("unavailable", "Fcitx is unavailable")
    return InputModeStatus("prepared", "Fcitx was deactivated")


def activate_game_input(
    paths: AppPaths, environment: Mapping[str, str]
) -> InputModeStatus:
    desktop = _desktop_paths(paths, environment)
    if desktop.transaction.exists():
        restored = restore_game_input(paths, environment)
        if restored.state == "unavailable":
            return restored
    if not _session_supported(environment):
        return InputModeStatus("unavailable", "Lubuntu X11 input profile is unavailable")
    try:
        snapshots = _capture_snapshots(desktop)
        profiles = {
            "openbox": _transform_openbox(_profile_source(desktop.openbox, desktop.system_openbox)),
            "lxqt": _transform_lxqt(_profile_source(desktop.lxqt, desktop.system_lxqt)),
        }
        _write_transaction(desktop.transaction, snapshots)
        _atomic_write(desktop.openbox, profiles["openbox"], _profile_mode(snapshots["openbox"]))
        _atomic_write(desktop.lxqt, profiles["lxqt"], _profile_mode(snapshots["lxqt"]))
        _reload_desktop(environment)
    except (InputModeError, OSError):
        if desktop.transaction.exists():
            try:
                _restore_snapshots(desktop, _read_transaction(desktop.transaction))
                _reload_desktop(environment, allow_failure=True)
                desktop.transaction.unlink(missing_ok=True)
            except (InputModeError, OSError):
                pass
        return InputModeStatus("unavailable", "Game input profile was not applied")
    return InputModeStatus("active", "Temporary game input profile is active")


def restore_game_input(
    paths: AppPaths, environment: Mapping[str, str]
) -> InputModeStatus:
    desktop = _desktop_paths(paths, environment)
    if not desktop.transaction.exists():
        return InputModeStatus("inactive", "No game input profile is active")
    try:
        snapshots = _read_transaction(desktop.transaction)
        _restore_snapshots(desktop, snapshots)
        if _session_supported(environment):
            _reload_desktop(environment)
        desktop.transaction.unlink()
    except (InputModeError, OSError):
        return InputModeStatus("unavailable", "Game input profile restoration failed")
    return InputModeStatus("inactive", "Game input profile was restored")


def game_input_status(
    paths: AppPaths, environment: Mapping[str, str]
) -> InputModeStatus:
    transaction = _desktop_paths(paths, environment).transaction
    if not transaction.exists():
        return InputModeStatus("inactive", "No game input profile is active")
    try:
        _read_transaction(transaction)
    except InputModeError:
        return InputModeStatus("malformed", "Game input profile state is malformed")
    return InputModeStatus("active", "Temporary game input profile is active")


def _desktop_paths(paths: AppPaths, environment: Mapping[str, str]) -> DesktopPaths:
    config = Path(environment.get("XDG_CONFIG_HOME", paths.home / ".config"))
    return DesktopPaths(
        openbox=config / "openbox/rc.xml",
        lxqt=config / "lxqt/globalkeyshortcuts.conf",
        system_openbox=SYSTEM_OPENBOX,
        system_lxqt=SYSTEM_LXQT,
        transaction=paths.state / "input-profile/active.json",
    )


def _session_supported(environment: Mapping[str, str]) -> bool:
    if (
        environment.get("XDG_SESSION_TYPE") != "x11"
        or not environment.get("DISPLAY")
        or not environment.get("XDG_RUNTIME_DIR")
    ):
        return False
    return _command_ok(["pgrep", "-x", "openbox"], environment) and _command_ok(
        ["pgrep", "-f", "^/usr/bin/lxqt-globalkeysd( |$)"], environment
    )


def _command_ok(argv: list[str], environment: Mapping[str, str]) -> bool:
    try:
        result = subprocess.run(
            argv,
            shell=False,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def _reload_desktop(environment: Mapping[str, str], *, allow_failure: bool = False) -> None:
    commands = (
        ["openbox", "--reconfigure"],
        ["systemctl", "--user", "restart", _LXQT_SERVICE],
        ["pgrep", "-f", "^/usr/bin/lxqt-globalkeysd( |$)"],
    )
    for argv in commands:
        if not _command_ok(argv, environment) and not allow_failure:
            raise InputModeError("desktop shortcut profile reload failed")


def _capture_snapshots(desktop: DesktopPaths) -> dict[str, FileSnapshot]:
    return {
        "openbox": _capture_file(desktop.openbox),
        "lxqt": _capture_file(desktop.lxqt),
    }


def _capture_file(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(False, b"", 0o600)
    if not path.is_file():
        raise InputModeError("desktop shortcut configuration is invalid")
    return FileSnapshot(True, path.read_bytes(), path.stat().st_mode & 0o777)


def _profile_source(target: Path, system: Path) -> bytes:
    if target.is_file():
        return target.read_bytes()
    if system.is_file():
        return system.read_bytes()
    raise InputModeError("desktop shortcut configuration is unavailable")


def _profile_mode(snapshot: FileSnapshot) -> int:
    return snapshot.mode if snapshot.existed else 0o600


def _write_transaction(path: Path, snapshots: Mapping[str, FileSnapshot]) -> None:
    payload = {
        "schema": 1,
        "files": {
            name: {
                "existed": snapshot.existed,
                "content": base64.b64encode(snapshot.content).decode("ascii"),
                "mode": snapshot.mode,
            }
            for name, snapshot in snapshots.items()
        },
    }
    _atomic_write(path, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"), 0o600)


def _read_transaction(path: Path) -> dict[str, FileSnapshot]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        files = payload["files"]
        if payload["schema"] != 1 or set(files) != {"openbox", "lxqt"}:
            raise ValueError
        return {
            name: FileSnapshot(
                bool(files[name]["existed"]),
                base64.b64decode(files[name]["content"], validate=True),
                int(files[name]["mode"]),
            )
            for name in ("openbox", "lxqt")
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputModeError("game input profile state is malformed") from exc


def _restore_snapshots(
    desktop: DesktopPaths, snapshots: Mapping[str, FileSnapshot]
) -> None:
    for target, snapshot in (
        (desktop.openbox, snapshots["openbox"]),
        (desktop.lxqt, snapshots["lxqt"]),
    ):
        if snapshot.existed:
            _atomic_write(target, snapshot.content, snapshot.mode)
        else:
            target.unlink(missing_ok=True)


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, raw_temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _transform_openbox(source: bytes) -> bytes:
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise InputModeError("Openbox keyboard configuration is malformed") from exc
    try:
        keyboard = next(
            node for node in root.iter() if _local_name(node.tag) == "keyboard"
        )
    except StopIteration as exc:
        raise InputModeError("Openbox keyboard configuration is malformed") from exc
    for binding in list(keyboard):
        if (
            _local_name(binding.tag) == "keybind"
            and binding.get("key") not in {"A-Tab", "A-S-Tab"}
        ):
            keyboard.remove(binding)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _transform_lxqt(source: bytes) -> bytes:
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(source.decode("utf-8"))
    except (UnicodeDecodeError, configparser.Error) as exc:
        raise InputModeError("LXQt shortcut configuration is malformed") from exc
    for section in parser.sections():
        if section != "General" and not section.startswith("XF86"):
            parser.set(section, "Enabled", "false")
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    return stream.getvalue().encode("utf-8")
