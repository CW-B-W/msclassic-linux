from __future__ import annotations

import json
import os
import re
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from .lockfile import Artifact
from .paths import AppPaths
from .runtime import diagnostic_runtime_root, diagnostic_runtime_valid


class InputDiagnosticError(ValueError):
    pass


DIAGNOSTIC_RECORD = struct.Struct("<QIHH")
CATEGORY_NAMES = {
    1: "xim_filtered_keyboard",
    2: "ime_open",
    3: "ime_closed",
    4: "composition_rect_set",
    5: "composition_rect_clear",
    6: "focus_in",
    7: "focus_out",
    8: "context_attached",
    9: "context_detached",
}
_MAX_LOG_SIZE = 64 * 1024 * 1024
_LOG_NAME = re.compile(r"input-[0-9]+\.bin\Z")


@dataclass(frozen=True)
class InputDiagnosticStatus:
    state: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"state": self.state, "detail": self.detail}


class InputDiagnosticSession:
    def __init__(
        self,
        paths: AppPaths,
        wine_root: Path,
        log_path: Path,
        descriptor: int,
    ) -> None:
        self.paths = paths
        self.wine_root = wine_root
        self.log_path = log_path
        self.descriptor = descriptor

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1
        _active_marker(self.paths).unlink(missing_ok=True)


def arm_input_diagnostic(
    paths: AppPaths, artifact: Artifact
) -> InputDiagnosticStatus:
    if not diagnostic_runtime_valid(paths, artifact):
        raise InputDiagnosticError("input diagnostic Wine runtime is unavailable")
    if _active_marker(paths).is_file():
        return InputDiagnosticStatus("capturing", "Input diagnostics are being captured")
    if _armed_marker(paths).is_file():
        return InputDiagnosticStatus("armed", "The next game launch will capture input event categories")
    directory = input_diagnostic_directory(paths)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_private_json(
        _armed_marker(paths),
        {"schema": 1, "log_name": f"input-{time.time_ns()}.bin"},
    )
    return InputDiagnosticStatus(
        "armed", "The next game launch will capture input event categories"
    )


def input_diagnostic_status(paths: AppPaths) -> InputDiagnosticStatus:
    if _active_marker(paths).is_file():
        return InputDiagnosticStatus("capturing", "Input diagnostics are being captured")
    if _armed_marker(paths).is_file():
        return InputDiagnosticStatus(
            "armed", "The next game launch will capture input event categories"
        )
    return InputDiagnosticStatus("inactive", "No input diagnostic is armed")


def stop_input_diagnostic(paths: AppPaths) -> InputDiagnosticStatus:
    if _active_marker(paths).is_file():
        return InputDiagnosticStatus(
            "capturing", "The active diagnostic stops when the game exits"
        )
    _armed_marker(paths).unlink(missing_ok=True)
    return InputDiagnosticStatus("inactive", "No input diagnostic is armed")


def start_armed_input_diagnostic(
    paths: AppPaths, artifact: Artifact
) -> InputDiagnosticSession | None:
    marker = _armed_marker(paths)
    if not marker.is_file():
        return None
    if not diagnostic_runtime_valid(paths, artifact):
        raise InputDiagnosticError("input diagnostic Wine runtime is unavailable")
    payload = _read_marker(marker)
    log_name = payload.get("log_name")
    if payload.get("schema") != 1 or not isinstance(log_name, str) or not _LOG_NAME.fullmatch(log_name):
        raise InputDiagnosticError("input diagnostic state is malformed")
    directory = input_diagnostic_directory(paths)
    log_path = directory / log_name
    try:
        descriptor = os.open(
            log_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        _write_private_json(_active_marker(paths), payload)
        marker.unlink()
    except OSError as exc:
        try:
            os.close(descriptor)
        except (NameError, OSError):
            pass
        log_path.unlink(missing_ok=True)
        raise InputDiagnosticError("input diagnostic session could not start") from exc
    return InputDiagnosticSession(
        paths,
        diagnostic_runtime_root(paths, artifact),
        log_path,
        descriptor,
    )


def input_diagnostic_directory(paths: AppPaths) -> Path:
    return paths.state / "input-diagnostic"


def _armed_marker(paths: AppPaths) -> Path:
    return input_diagnostic_directory(paths) / "armed.json"


def _active_marker(paths: AppPaths) -> Path:
    return input_diagnostic_directory(paths) / "active.json"


def _read_marker(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 4096:
            raise InputDiagnosticError("input diagnostic state is malformed")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputDiagnosticError("input diagnostic state is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "log_name"}:
        raise InputDiagnosticError("input diagnostic state is malformed")
    return payload


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
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


def parse_diagnostic_records(
    path: Path, diagnostic_directory: Path
) -> tuple[tuple[int, int, int], ...]:
    try:
        directory = diagnostic_directory.resolve(strict=True)
        if path.is_symlink() or path.parent.resolve(strict=True) != directory:
            raise InputDiagnosticError("input diagnostic path is invalid")
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise InputDiagnosticError("input diagnostic file is not private")
        if metadata.st_size > _MAX_LOG_SIZE or metadata.st_size % DIAGNOSTIC_RECORD.size:
            raise InputDiagnosticError("input diagnostic file is malformed")
        content = path.read_bytes()
    except InputDiagnosticError:
        raise
    except OSError as exc:
        raise InputDiagnosticError("input diagnostic file is unavailable") from exc

    records: list[tuple[int, int, int]] = []
    for offset in range(0, len(content), DIAGNOSTIC_RECORD.size):
        monotonic_ns, sequence, category, schema = DIAGNOSTIC_RECORD.unpack_from(
            content, offset
        )
        if schema != 1 or category not in CATEGORY_NAMES:
            raise InputDiagnosticError("input diagnostic file is malformed")
        records.append((monotonic_ns, sequence, category))
    return tuple(records)


def summarize_diagnostic(path: Path, diagnostic_directory: Path) -> dict[str, object]:
    records = parse_diagnostic_records(path, diagnostic_directory)
    counts = {name: 0 for name in CATEGORY_NAMES.values()}
    for _timestamp, _sequence, category in records:
        counts[CATEGORY_NAMES[category]] += 1
    duration = 0
    if records:
        duration = max(timestamp for timestamp, _sequence, _category in records) - min(
            timestamp for timestamp, _sequence, _category in records
        )
    return {
        "schema": 1,
        "records": len(records),
        "duration_ns": duration,
        "counts": counts,
    }
