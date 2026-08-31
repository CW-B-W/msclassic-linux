from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .doctor import GraphicsReport, collect_graphics_report, evaluate_launch_graphics
from .paths import AppPaths
from .redaction import assert_export_safe


class GraphicsApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovalResult:
    reused: bool
    boot_id: str


def read_boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError as exc:
        raise GraphicsApprovalError("graphics launch check failed") from exc
    if not value or len(value) > 128:
        raise GraphicsApprovalError("graphics launch check failed")
    return value


def ensure_current_boot_approval(
    paths: AppPaths,
    collector: Callable[[AppPaths], GraphicsReport] = collect_graphics_report,
    *,
    boot_id_reader: Callable[[], str] = read_boot_id,
) -> ApprovalResult:
    """Reuse a current stamp or run the launch graphics gate exactly once."""

    try:
        current_boot = boot_id_reader()
    except GraphicsApprovalError:
        raise
    except Exception as exc:
        raise GraphicsApprovalError("graphics launch check failed") from exc
    stamp_path = paths.state / "graphics-ok.json"
    if _stamp_matches(stamp_path, current_boot):
        return ApprovalResult(True, current_boot)

    # A stale approval must never survive a failed recheck.
    try:
        stamp_path.unlink(missing_ok=True)
        report = collector(paths)
        passed, _ = evaluate_launch_graphics(report)
        if not passed or report.boot_id != current_boot:
            raise GraphicsApprovalError("graphics launch check failed")
        write_graphics_approval(paths, report)
    except GraphicsApprovalError:
        stamp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        stamp_path.unlink(missing_ok=True)
        raise GraphicsApprovalError("graphics launch check failed") from exc
    return ApprovalResult(False, current_boot)


def write_graphics_approval(paths: AppPaths, report: GraphicsReport) -> None:
    passed, _ = evaluate_launch_graphics(report)
    if not passed or not report.boot_id or len(report.boot_id) > 128:
        raise GraphicsApprovalError("graphics launch check failed")
    payload = {"schema": 1, "gate_passed": True, "boot_id": report.boot_id}
    assert_export_safe(payload)
    paths.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = paths.state / "graphics-ok.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".graphics-ok-",
        suffix=".json.tmp",
        dir=paths.state,
    )
    temporary = Path(temporary_name)
    os.fchmod(descriptor, 0o600)
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


def invalidate_graphics_approval(paths: AppPaths) -> None:
    try:
        (paths.state / "graphics-ok.json").unlink(missing_ok=True)
    except OSError as exc:
        raise GraphicsApprovalError("graphics launch check failed") from exc


def _stamp_matches(path: Path, boot_id: str) -> bool:
    try:
        if path.stat().st_size > 16_384:
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value == {"schema": 1, "gate_passed": True, "boot_id": boot_id}
