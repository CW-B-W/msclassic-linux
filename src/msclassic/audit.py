from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .commands import CommandResult
from .redaction import assert_export_safe


class TrialError(ValueError):
    pass


class DriftError(TrialError):
    pass


@dataclass(frozen=True)
class TrialSpec:
    name: str
    hypothesis: str
    variable: str
    before: str
    after: str
    expected: str
    pass_rule: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", self.name):
            raise TrialError("trial name is invalid")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.variable):
            raise TrialError("trial must name exactly one variable")
        for value in (self.hypothesis, self.before, self.after, self.expected, self.pass_rule):
            if not value.strip():
                raise TrialError("trial fields cannot be empty")
            assert_export_safe(value)


class TrialRecorder:
    def __init__(self, runs: Path, clock: Callable[[], datetime] | None = None):
        self.runs = runs
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.spec: TrialSpec | None = None
        self.baseline: dict[str, object] = {}
        self.command_results: list[CommandResult] = []
        self.observations: list[str] = []
        self.started_at = ""

    def begin(self, spec: TrialSpec, baseline: Mapping[str, object]) -> "TrialRecorder":
        assert_export_safe(baseline)
        self.spec = spec
        self.baseline = dict(baseline)
        self.command_results = []
        self.observations = []
        self.started_at = self.clock().isoformat()
        return self

    def record(self, result: CommandResult) -> None:
        if self.spec is None:
            raise TrialError("trial has not begun")
        assert_export_safe(asdict(result))
        self.command_results.append(result)

    def observe(self, text: str) -> None:
        if self.spec is None:
            raise TrialError("trial has not begun")
        assert_export_safe(text)
        self.observations.append(text)

    def finish(self, disposition: str) -> Path:
        if self.spec is None:
            raise TrialError("trial has not begun")
        if disposition not in {"rejected", "inconclusive", "candidate", "reference"}:
            raise TrialError("invalid trial disposition")
        timestamp = self.clock()
        run_name = f"{timestamp:%Y%m%d-%H%M%S}-{self.spec.name}"
        run_dir = self.runs / run_name
        run_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(run_dir, 0o700)
        manifest = {
            "schema": 1,
            "started_at": self.started_at,
            "finished_at": timestamp.isoformat(),
            "trial": asdict(self.spec),
            "baseline": self.baseline,
            "commands": [asdict(result) for result in self.command_results],
            "observations": list(self.observations),
            "disposition": disposition,
        }
        assert_export_safe(manifest)
        _private_atomic_write(
            run_dir / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )
        report_lines = [
            f"# Trial: {self.spec.name}",
            "",
            f"- Hypothesis: {self.spec.hypothesis}",
            f"- Variable: {self.spec.variable}",
            f"- Before: {self.spec.before}",
            f"- After: {self.spec.after}",
            f"- Expected: {self.spec.expected}",
            f"- Pass rule: {self.spec.pass_rule}",
            f"- Disposition: {disposition}",
            "",
            "## Observations",
            "",
            *([f"- {item}" for item in self.observations] or ["- No live observation recorded."]),
            "",
        ]
        _private_atomic_write(run_dir / "report.md", "\n".join(report_lines))
        return run_dir


def compare_reference(
    reference: Mapping[str, object],
    candidate: Mapping[str, object],
    accept_drift: bool,
) -> list[str]:
    keys = sorted(set(reference) | set(candidate))
    drift = [key for key in keys if reference.get(key) != candidate.get(key)]
    if drift and not accept_drift:
        raise DriftError("unexplained drift: " + ", ".join(drift))
    return drift


def _private_atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise

