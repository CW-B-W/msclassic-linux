from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .base import PlatformAdapter
from .lubuntu_2404 import LUBUNTU_2404


class UnsupportedPlatformError(ValueError):
    pass


_SUPPORTED = {LUBUNTU_2404.id: LUBUNTU_2404}
_UNSUPPORTED_MESSAGE = "unsupported platform; currently supported: lubuntu-24.04"


def select_platform(
    requested: str | None,
    os_release: Mapping[str, str],
) -> PlatformAdapter:
    """Select only an adapter that matches both the request and operating system."""

    adapter = _SUPPORTED.get(requested) if requested is not None else LUBUNTU_2404
    if adapter is None or not adapter.matches(dict(os_release)):
        raise UnsupportedPlatformError(_UNSUPPORTED_MESSAGE)
    return adapter


def read_os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise UnsupportedPlatformError(_UNSUPPORTED_MESSAGE) from exc
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key in {"ID", "VERSION_ID", "ID_LIKE"}:
            values[key] = value.strip().strip('"').strip("'")
    return values


__all__ = [
    "LUBUNTU_2404",
    "PlatformAdapter",
    "UnsupportedPlatformError",
    "read_os_release",
    "select_platform",
]
