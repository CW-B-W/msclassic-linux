from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .redaction import UnsafeExportError, assert_export_safe, sanitize_text


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class CommandResult:
    category: str
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str


def run_allowlisted(
    category: str,
    argv: Sequence[str],
    allowed_binaries: set[Path],
    *,
    timeout: float = 30.0,
) -> CommandResult:
    if not category or not argv:
        raise CommandError("command category and argv are required")
    executable = _resolve_executable(argv[0])
    allowed = {path.resolve() for path in allowed_binaries}
    if executable not in allowed:
        raise CommandError("binary is not allowlisted")
    try:
        assert_export_safe(list(argv))
    except UnsafeExportError as exc:
        raise CommandError("sensitive argv cannot be audited") from exc
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [str(executable), *argv[1:]],
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f"command timed out in category {category}") from exc
    return CommandResult(
        category=category,
        exit_code=completed.returncode,
        duration_ms=round((time.monotonic() - started) * 1000),
        stdout=sanitize_text(completed.stdout[:65_536]),
        stderr=sanitize_text(completed.stderr[:65_536]),
    )


def _resolve_executable(value: str) -> Path:
    if "/" in value:
        return Path(value).resolve()
    resolved = shutil.which(value)
    if resolved is None:
        raise CommandError("binary not found")
    return Path(resolved).resolve()
