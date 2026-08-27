from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformAdapter:
    """Distribution-specific installation metadata used by the neutral core."""

    id: str
    os_id: str
    version_id: str
    package_names: tuple[str, ...]
    chromium_policy_dir: str

    def matches(self, os_release: dict[str, str]) -> bool:
        return (
            os_release.get("ID", "").lower() == self.os_id
            and os_release.get("VERSION_ID") == self.version_id
        )
