from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence


class UnsafeExportError(ValueError):
    pass


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "otp",
    "passarg",
    "serviceaccount",
    "token",
}
_NEXONPLUG_URI = re.compile(r"(?i)nexonplug:[^\s]*")
_NGM_URI = re.compile(r"(?i)ngm://launch/ ?[^\s]*")
_NAMED = re.compile(
    r"(?i)\b(passarg|otp|cookie|authorization|serviceaccount|token)\s*[:=]\s*[^\s,;}]+"
)


def sanitize_text(text: str) -> str:
    safe = _NGM_URI.sub("[REDACTED_LAUNCH_URI]", str(text))
    safe = _NEXONPLUG_URI.sub("[REDACTED_NEXONPLUG_URI]", safe)
    return _NAMED.sub(lambda match: f"{match.group(1)}=[REDACTED]", safe)


def assert_export_safe(value: object) -> None:
    _inspect(value)
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if _NEXONPLUG_URI.search(serialized) or _NGM_URI.search(serialized) or _NAMED.search(serialized):
        raise UnsafeExportError("export contains sensitive launch material")


def _inspect(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in _SENSITIVE_KEYS:
                raise UnsafeExportError("export contains a sensitive key")
            _inspect(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _inspect(child)
    elif isinstance(value, str):
        if _NEXONPLUG_URI.search(value) or _NGM_URI.search(value) or _NAMED.search(value):
            raise UnsafeExportError("export contains sensitive launch material")
