from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import AppPaths


class ProfilerError(ValueError):
    pass


@dataclass(frozen=True)
class ProfilerStatus:
    state: str
    detail: str

    def to_json(self) -> dict[str, str]:
        return {"state": self.state, "detail": self.detail}


@dataclass(frozen=True)
class RawCounters:
    swap_in_pages: int
    swap_out_pages: int
    cpu_iowait_ticks: int
    disk_read_bytes: int
    disk_write_bytes: int


_LOG_NAME = re.compile(r"profile-[0-9]+\.jsonl\Z")
_SAMPLE_KEYS = {
    "schema",
    "monotonic_ns",
    "process_cpu_ticks",
    "process_rss_kb",
    "guest_mem_total_kb",
    "guest_mem_available_kb",
    "swap_total_kb",
    "swap_free_kb",
    "swap_in_pages_delta",
    "swap_out_pages_delta",
    "cpu_iowait_ticks_delta",
    "psi_cpu_some_total_us",
    "psi_cpu_full_total_us",
    "psi_cpu_available",
    "psi_io_some_total_us",
    "psi_io_full_total_us",
    "psi_io_available",
    "psi_memory_some_total_us",
    "psi_memory_full_total_us",
    "psi_memory_available",
    "disk_read_bytes_delta",
    "disk_write_bytes_delta",
    "balloon_target_kb",
    "balloon_available",
}


def parse_meminfo(text: str) -> tuple[int, int, int, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].endswith(":"):
            name = fields[0][:-1]
            if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                try:
                    values[name] = int(fields[1], 10)
                except ValueError as exc:
                    raise ValueError("proc meminfo is malformed") from exc
    try:
        return (
            values["MemTotal"],
            values["MemAvailable"],
            values["SwapTotal"],
            values["SwapFree"],
        )
    except KeyError as exc:
        raise ValueError("proc meminfo is incomplete") from exc


def parse_cpu_stat(text: str) -> int:
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == "cpu" and len(fields) >= 6:
            try:
                return int(fields[5], 10)
            except ValueError as exc:
                raise ValueError("proc cpu stat is malformed") from exc
    raise ValueError("proc cpu stat is incomplete")


def parse_vmstat(text: str) -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in {"pswpin", "pswpout"}:
            try:
                values[fields[0]] = int(fields[1], 10)
            except ValueError as exc:
                raise ValueError("proc vmstat is malformed") from exc
    try:
        return values["pswpin"], values["pswpout"]
    except KeyError as exc:
        raise ValueError("proc vmstat is incomplete") from exc


def parse_psi(text: str) -> tuple[int, int, bool]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in {"some", "full"}:
            continue
        total = next((field for field in fields[1:] if field.startswith("total=")), None)
        if total is None:
            continue
        try:
            values[fields[0]] = int(total.partition("=")[2], 10)
        except ValueError:
            return 0, 0, False
    if "some" not in values:
        return 0, 0, False
    return values["some"], values.get("full", 0), True


def parse_diskstats(text: str) -> tuple[int, int]:
    sectors_read = 0
    sectors_written = 0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 10:
            continue
        name = fields[2]
        if name.startswith(("loop", "ram", "fd", "sr")):
            continue
        try:
            sectors_read += int(fields[5], 10)
            sectors_written += int(fields[9], 10)
        except ValueError:
            continue
    return sectors_read * 512, sectors_written * 512


def collect_numeric_sample(
    *,
    monotonic_ns: int,
    meminfo: tuple[int, int, int, int],
    process_totals: tuple[int, int],
    psi: tuple[int, int, bool, int, int, bool, int, int, bool],
    counters: RawCounters,
    previous: RawCounters | None,
    balloon: tuple[int, bool],
) -> dict[str, int | bool]:
    prior = previous or counters

    def delta(current: int, old: int) -> int:
        return max(0, current - old)

    sample: dict[str, int | bool] = {
        "schema": 1,
        "monotonic_ns": int(monotonic_ns),
        "process_cpu_ticks": int(process_totals[0]),
        "process_rss_kb": int(process_totals[1]),
        "guest_mem_total_kb": int(meminfo[0]),
        "guest_mem_available_kb": int(meminfo[1]),
        "swap_total_kb": int(meminfo[2]),
        "swap_free_kb": int(meminfo[3]),
        "swap_in_pages_delta": delta(counters.swap_in_pages, prior.swap_in_pages),
        "swap_out_pages_delta": delta(counters.swap_out_pages, prior.swap_out_pages),
        "cpu_iowait_ticks_delta": delta(counters.cpu_iowait_ticks, prior.cpu_iowait_ticks),
        "psi_cpu_some_total_us": int(psi[0]),
        "psi_cpu_full_total_us": int(psi[1]),
        "psi_cpu_available": bool(psi[2]),
        "psi_io_some_total_us": int(psi[3]),
        "psi_io_full_total_us": int(psi[4]),
        "psi_io_available": bool(psi[5]),
        "psi_memory_some_total_us": int(psi[6]),
        "psi_memory_full_total_us": int(psi[7]),
        "psi_memory_available": bool(psi[8]),
        "disk_read_bytes_delta": delta(counters.disk_read_bytes, prior.disk_read_bytes),
        "disk_write_bytes_delta": delta(counters.disk_write_bytes, prior.disk_write_bytes),
        "balloon_target_kb": int(balloon[0]),
        "balloon_available": bool(balloon[1]),
    }
    _validate_sample(sample)
    return sample


def arm_profile(paths: AppPaths) -> ProfilerStatus:
    directory = _profile_directory(paths)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _capturing_marker(paths).exists():
        return ProfilerStatus("capturing", "A numeric performance profile is being captured")
    payload = {
        "schema": 1,
        "log_name": f"profile-{time.time_ns()}.jsonl",
    }
    _atomic_private_json(_armed_marker(paths), payload)
    return ProfilerStatus("armed", "The next game launch will capture numeric performance data")


def profile_status(paths: AppPaths) -> ProfilerStatus:
    if _capturing_marker(paths).is_file():
        return ProfilerStatus("capturing", "A numeric performance profile is being captured")
    if _armed_marker(paths).is_file():
        return ProfilerStatus("armed", "The next game launch will capture numeric performance data")
    return ProfilerStatus("inactive", "No performance profile is armed")


def stop_profile(paths: AppPaths) -> ProfilerStatus:
    _armed_marker(paths).unlink(missing_ok=True)
    _capturing_marker(paths).unlink(missing_ok=True)
    return ProfilerStatus("inactive", "Performance profiling is inactive")


def start_armed_profiler(
    paths: AppPaths,
    *,
    sample_source: Callable[[RawCounters | None], tuple[dict[str, int | bool], RawCounters | None]] | None = None,
    interval: float = 1.0,
) -> PerformanceProfiler | None:
    marker = _armed_marker(paths)
    if not marker.is_file():
        return None
    payload = _read_marker(marker)
    log_name = payload.get("log_name")
    if payload.get("schema") != 1 or not isinstance(log_name, str) or not _LOG_NAME.fullmatch(log_name):
        raise ProfilerError("performance profile state is malformed")
    profiler = PerformanceProfiler(
        paths,
        log_path=_profile_directory(paths) / log_name,
        sample_source=sample_source,
        interval=interval,
    )
    profiler.start()
    return profiler


class PerformanceProfiler:
    def __init__(
        self,
        paths: AppPaths,
        *,
        log_path: Path,
        sample_source: Callable[[RawCounters | None], tuple[dict[str, int | bool], RawCounters | None]] | None = None,
        interval: float = 1.0,
    ) -> None:
        if interval <= 0:
            raise ProfilerError("profile interval must be positive")
        self.paths = paths
        self.log_path = log_path
        self.sample_source = sample_source or _live_sample
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None

    def start(self) -> None:
        if self._thread is not None:
            raise ProfilerError("performance profiler is already running")
        directory = _profile_directory(self.paths)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.log_path.parent != directory or not _LOG_NAME.fullmatch(self.log_path.name):
            raise ProfilerError("performance profile path is invalid")
        descriptor = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
        self._stream = os.fdopen(descriptor, "w", encoding="utf-8")
        _atomic_private_json(
            _capturing_marker(self.paths),
            {"schema": 1, "log_name": self.log_path.name},
        )
        _armed_marker(self.paths).unlink(missing_ok=True)
        self._thread = threading.Thread(
            target=self._run,
            name="msclassic-numeric-profiler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval * 2))
            if self._thread.is_alive():
                raise ProfilerError("performance profiler did not stop")
        _capturing_marker(self.paths).unlink(missing_ok=True)

    def _run(self) -> None:
        previous: RawCounters | None = None
        try:
            while not self._stop.is_set() and _capturing_marker(self.paths).exists():
                try:
                    sample, previous = self.sample_source(previous)
                    _validate_sample(sample)
                    assert self._stream is not None
                    self._stream.write(json.dumps(sample, sort_keys=True, separators=(",", ":")) + "\n")
                    self._stream.flush()
                except (OSError, ValueError):
                    pass
                self._stop.wait(self.interval)
        finally:
            if self._stream is not None:
                self._stream.close()
            _capturing_marker(self.paths).unlink(missing_ok=True)


def _live_sample(previous: RawCounters | None) -> tuple[dict[str, int | bool], RawCounters]:
    proc = Path("/proc")
    meminfo = parse_meminfo((proc / "meminfo").read_text(encoding="ascii"))
    swap_in, swap_out = parse_vmstat((proc / "vmstat").read_text(encoding="ascii"))
    iowait = parse_cpu_stat((proc / "stat").read_text(encoding="ascii"))
    disk_read, disk_write = parse_diskstats((proc / "diskstats").read_text(encoding="ascii"))
    counters = RawCounters(swap_in, swap_out, iowait, disk_read, disk_write)
    cpu_psi = _read_psi(proc / "pressure/cpu")
    io_psi = _read_psi(proc / "pressure/io")
    memory_psi = _read_psi(proc / "pressure/memory")
    sample = collect_numeric_sample(
        monotonic_ns=time.monotonic_ns(),
        meminfo=meminfo,
        process_totals=_read_game_process_totals(proc),
        psi=(*cpu_psi, *io_psi, *memory_psi),
        counters=counters,
        previous=previous,
        balloon=_read_balloon_target(),
    )
    return sample, counters


def _read_game_process_totals(proc: Path) -> tuple[int, int]:
    cpu_ticks = 0
    rss_kb = 0
    for process in proc.iterdir():
        if not process.name.isdecimal():
            continue
        try:
            name = (process / "comm").read_text(encoding="ascii").strip().lower()
            if name != "wineserver" and not name.startswith("maplestory_clas"):
                continue
            raw_stat = (process / "stat").read_text(encoding="ascii")
            fields = raw_stat[raw_stat.rfind(")") + 2 :].split()
            cpu_ticks += int(fields[11], 10) + int(fields[12], 10)
            for line in (process / "status").read_text(encoding="ascii").splitlines():
                if line.startswith("VmRSS:"):
                    rss_kb += int(line.split()[1], 10)
                    break
        except (OSError, UnicodeError, ValueError, IndexError):
            continue
    return cpu_ticks, rss_kb


def _read_psi(path: Path) -> tuple[int, int, bool]:
    try:
        return parse_psi(path.read_text(encoding="ascii"))
    except OSError:
        return 0, 0, False


def _read_balloon_target() -> tuple[int, bool]:
    for candidate in (
        Path("/sys/kernel/debug/virtio-balloon/target_kb"),
        Path("/sys/devices/virtual/virtio_balloon/target_kb"),
    ):
        try:
            return int(candidate.read_text(encoding="ascii").strip(), 10), True
        except (OSError, ValueError):
            continue
    return 0, False


def _validate_sample(sample: dict[str, int | bool]) -> None:
    if set(sample) != _SAMPLE_KEYS or any(
        type(value) not in {int, float, bool} for value in sample.values()
    ):
        raise ProfilerError("performance sample is malformed")


def _profile_directory(paths: AppPaths) -> Path:
    return paths.state / "performance-profile"


def _armed_marker(paths: AppPaths) -> Path:
    return _profile_directory(paths) / "armed.json"


def _capturing_marker(paths: AppPaths) -> Path:
    return _profile_directory(paths) / "capturing.json"


def _read_marker(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 4096:
            raise ProfilerError("performance profile state is malformed")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfilerError("performance profile state is malformed") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema", "log_name"}:
        raise ProfilerError("performance profile state is malformed")
    return payload


def _atomic_private_json(path: Path, payload: dict[str, object]) -> None:
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
