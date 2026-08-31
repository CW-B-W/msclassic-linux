from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class AppPaths:
    home: Path
    config: Path
    data: Path
    state: Path
    cache: Path
    client: Path
    prefix: Path
    runs: Path
    tools: Path

    @classmethod
    def from_environment(cls, env: Mapping[str, str]) -> "AppPaths":
        try:
            home = Path(env["HOME"]).expanduser()
        except KeyError as exc:
            raise ValueError("HOME is required") from exc
        config_base = Path(env.get("XDG_CONFIG_HOME", home / ".config"))
        data_base = Path(env.get("XDG_DATA_HOME", home / ".local/share"))
        state_base = Path(env.get("XDG_STATE_HOME", home / ".local/state"))
        cache_base = Path(env.get("XDG_CACHE_HOME", home / ".cache"))
        config = config_base / "maplestory-classic"
        data = data_base / "maplestory-classic"
        state = state_base / "maplestory-classic"
        cache = cache_base / "maplestory-classic"
        return cls(
            home=home,
            config=config,
            data=data,
            state=state,
            cache=cache,
            client=home / "Games/MapleStoryClassic",
            prefix=data / "prefix-wine1110",
            runs=state / "runs",
            tools=data / "tools",
        )
