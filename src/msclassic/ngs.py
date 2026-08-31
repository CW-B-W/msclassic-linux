from __future__ import annotations

from dataclasses import dataclass

from .paths import AppPaths


@dataclass(frozen=True)
class NgsState:
    rpcss_registered: bool
    plugplay_registered: bool
    ngs_registered: bool
    broker_installed: bool

    @property
    def complete(self) -> bool:
        return all(
            (
                self.rpcss_registered,
                self.plugplay_registered,
                self.ngs_registered,
                self.broker_installed,
            )
        )


def inspect_ngs_state(paths: AppPaths) -> NgsState:
    try:
        registry = (paths.prefix / "system.reg").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        registry = ""
    return NgsState(
        rpcss_registered=_service_registered(registry, "RpcSs"),
        plugplay_registered=_service_registered(registry, "PlugPlay"),
        ngs_registered=_service_registered(registry, "NGS"),
        broker_installed=(
            paths.prefix
            / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
        ).is_file(),
    )


def _service_registered(registry: str, name: str) -> bool:
    heading = f"[System\\\\ControlSet001\\\\Services\\\\{name}]"
    return heading in registry
