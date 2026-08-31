from __future__ import annotations

import base64
import json
import os
import shlex
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
class LxqtAction:
    action_id: int
    shortcut: str
    description: str
    enabled: bool
    action_type: str
    target: str


@dataclass(frozen=True)
class DesktopPaths:
    openbox: Path
    system_openbox: Path
    transaction: Path


@dataclass(frozen=True)
class FileSnapshot:
    existed: bool
    content: bytes
    mode: int


@dataclass(frozen=True)
class InputTransaction:
    openbox: FileSnapshot
    lxqt_actions: tuple[tuple[int, bool], ...]


SYSTEM_OPENBOX = Path("/etc/xdg/openbox/rc.xml")
_LXQT_SERVICE = "org.lxqt.global_key_shortcuts"
_LXQT_PATH = "/daemon"
_LXQT_INTERFACE = "org.lxqt.global_key_shortcuts.daemon"
_LXQT_SIGNATURE = "a{t(ssbss)}"


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

    openbox = _capture_file(desktop.openbox)
    profile = _transform_openbox(_profile_source(desktop.openbox, desktop.system_openbox))
    lxqt_available = True
    try:
        actions = _list_lxqt_actions(environment)
    except InputModeError:
        actions = ()
        lxqt_available = False
    transaction = InputTransaction(
        openbox,
        tuple((action.action_id, action.enabled) for action in actions),
    )

    try:
        _write_transaction(desktop.transaction, transaction)
        _atomic_write(desktop.openbox, profile, _profile_mode(openbox))
        _reload_openbox(environment)
    except (InputModeError, OSError):
        _restore_after_activation_failure(desktop, transaction, environment)
        return InputModeStatus("unavailable", "Game input profile was not applied")

    changed: list[tuple[int, bool]] = []
    if lxqt_available:
        try:
            for action in actions:
                if action.enabled and not _is_hardware_action(action):
                    changed.append((action.action_id, action.enabled))
                    _set_lxqt_action_enabled(action.action_id, False, environment)
        except InputModeError:
            for action_id, enabled in reversed(changed):
                try:
                    _set_lxqt_action_enabled(action_id, enabled, environment)
                except InputModeError:
                    pass
            lxqt_available = False
            transaction = InputTransaction(openbox, ())
            try:
                _write_transaction(desktop.transaction, transaction)
            except OSError:
                _restore_after_activation_failure(desktop, transaction, environment)
                return InputModeStatus("unavailable", "Game input profile was not applied")

    if not lxqt_available:
        return InputModeStatus(
            "active",
            "Temporary Openbox profile is active; LXQt shortcuts unavailable",
        )
    return InputModeStatus("active", "Temporary game input profile is active")


def restore_game_input(
    paths: AppPaths, environment: Mapping[str, str]
) -> InputModeStatus:
    desktop = _desktop_paths(paths, environment)
    if not desktop.transaction.exists():
        return InputModeStatus("inactive", "No game input profile is active")
    try:
        transaction = _read_transaction(desktop.transaction)
    except InputModeError:
        return InputModeStatus("unavailable", "Game input profile restoration failed")

    failed = False
    try:
        _restore_file(desktop.openbox, transaction.openbox)
        if _session_supported(environment):
            _reload_openbox(environment)
    except (InputModeError, OSError):
        failed = True
    for action_id, enabled in transaction.lxqt_actions:
        try:
            _set_lxqt_action_enabled(action_id, enabled, environment)
        except InputModeError:
            failed = True
    if failed:
        return InputModeStatus("unavailable", "Game input profile restoration failed")
    try:
        desktop.transaction.unlink()
    except OSError:
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
        system_openbox=SYSTEM_OPENBOX,
        transaction=paths.state / "input-profile/active.json",
    )


def _session_supported(environment: Mapping[str, str]) -> bool:
    if (
        environment.get("XDG_SESSION_TYPE") != "x11"
        or not environment.get("DISPLAY")
        or not environment.get("XDG_RUNTIME_DIR")
    ):
        return False
    return _command_ok(["pgrep", "-x", "openbox"], environment)


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


def _reload_openbox(
    environment: Mapping[str, str], *, allow_failure: bool = False
) -> None:
    if not _command_ok(["openbox", "--reconfigure"], environment) and not allow_failure:
        raise InputModeError("Openbox shortcut profile reload failed")


def _list_lxqt_actions(environment: Mapping[str, str]) -> tuple[LxqtAction, ...]:
    result = _busctl(
        [
            "call",
            _LXQT_SERVICE,
            _LXQT_PATH,
            _LXQT_INTERFACE,
            "getAllActions",
        ],
        environment,
    )
    return _parse_lxqt_actions(result.stdout)


def _set_lxqt_action_enabled(
    action_id: int, enabled: bool, environment: Mapping[str, str]
) -> None:
    result = _busctl(
        [
            "call",
            _LXQT_SERVICE,
            _LXQT_PATH,
            _LXQT_INTERFACE,
            "enableAction",
            "tb",
            str(action_id),
            "true" if enabled else "false",
        ],
        environment,
    )
    if result.stdout.split() != ["b", "true"]:
        raise InputModeError("LXQt shortcut state change failed")


def _busctl(
    arguments: list[str], environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["busctl", "--user", *arguments],
            shell=False,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise InputModeError("LXQt shortcut D-Bus interface is unavailable") from exc
    if result.returncode != 0:
        raise InputModeError("LXQt shortcut D-Bus operation failed")
    return result


def _parse_lxqt_actions(output: str) -> tuple[LxqtAction, ...]:
    try:
        fields = shlex.split(output, posix=True)
    except ValueError as exc:
        raise InputModeError("LXQt shortcut reply is malformed") from exc
    if len(fields) < 2 or fields[0] != _LXQT_SIGNATURE:
        raise InputModeError("LXQt shortcut reply is malformed")
    try:
        count = int(fields[1], 10)
    except ValueError as exc:
        raise InputModeError("LXQt shortcut reply is malformed") from exc
    if count < 0 or count > 4096 or len(fields) != 2 + count * 6:
        raise InputModeError("LXQt shortcut reply is malformed")

    actions: list[LxqtAction] = []
    seen: set[int] = set()
    for offset in range(2, len(fields), 6):
        raw_id, shortcut, description, raw_enabled, action_type, target = fields[
            offset : offset + 6
        ]
        try:
            action_id = int(raw_id, 10)
        except ValueError as exc:
            raise InputModeError("LXQt shortcut reply is malformed") from exc
        if (
            action_id < 0
            or action_id > (2**64 - 1)
            or action_id in seen
            or raw_enabled not in {"true", "false"}
        ):
            raise InputModeError("LXQt shortcut reply is malformed")
        seen.add(action_id)
        actions.append(
            LxqtAction(
                action_id,
                shortcut,
                description,
                raw_enabled == "true",
                action_type,
                target,
            )
        )
    return tuple(actions)


def _is_hardware_action(action: LxqtAction) -> bool:
    if action.shortcut.startswith("XF86"):
        return True
    try:
        command = shlex.split(action.target, posix=True)
    except ValueError:
        return False
    return bool(command) and Path(command[0]).name == "lxqt-config-brightness"


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


def _write_transaction(path: Path, transaction: InputTransaction) -> None:
    payload = {
        "schema": 2,
        "openbox": {
            "existed": transaction.openbox.existed,
            "content": base64.b64encode(transaction.openbox.content).decode("ascii"),
            "mode": transaction.openbox.mode,
        },
        "lxqt_actions": [
            {"id": action_id, "enabled": enabled}
            for action_id, enabled in transaction.lxqt_actions
        ],
    }
    _atomic_write(
        path,
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"),
        0o600,
    )


def _read_transaction(path: Path) -> InputTransaction:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "schema",
            "openbox",
            "lxqt_actions",
        }:
            raise ValueError
        if payload["schema"] != 2:
            raise ValueError
        raw_openbox = payload["openbox"]
        if not isinstance(raw_openbox, dict) or set(raw_openbox) != {
            "existed",
            "content",
            "mode",
        }:
            raise ValueError
        if type(raw_openbox["existed"]) is not bool:
            raise ValueError
        mode = raw_openbox["mode"]
        if type(mode) is not int or mode < 0 or mode > 0o777:
            raise ValueError
        openbox = FileSnapshot(
            raw_openbox["existed"],
            base64.b64decode(raw_openbox["content"], validate=True),
            mode,
        )
        raw_actions = payload["lxqt_actions"]
        if not isinstance(raw_actions, list) or len(raw_actions) > 4096:
            raise ValueError
        actions: list[tuple[int, bool]] = []
        seen: set[int] = set()
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict) or set(raw_action) != {"id", "enabled"}:
                raise ValueError
            action_id = raw_action["id"]
            enabled = raw_action["enabled"]
            if (
                type(action_id) is not int
                or action_id < 0
                or action_id > (2**64 - 1)
                or action_id in seen
                or type(enabled) is not bool
            ):
                raise ValueError
            seen.add(action_id)
            actions.append((action_id, enabled))
        return InputTransaction(openbox, tuple(actions))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputModeError("game input profile state is malformed") from exc


def _restore_after_activation_failure(
    desktop: DesktopPaths,
    transaction: InputTransaction,
    environment: Mapping[str, str],
) -> None:
    try:
        _restore_file(desktop.openbox, transaction.openbox)
        _reload_openbox(environment, allow_failure=True)
    except (InputModeError, OSError):
        pass
    for action_id, enabled in transaction.lxqt_actions:
        try:
            _set_lxqt_action_enabled(action_id, enabled, environment)
        except InputModeError:
            pass
    desktop.transaction.unlink(missing_ok=True)


def _restore_file(target: Path, snapshot: FileSnapshot) -> None:
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
