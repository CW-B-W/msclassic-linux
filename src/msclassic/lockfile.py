from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class LockfileError(ValueError):
    pass


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    url: str
    algorithm: str
    digest: str
    size: int


_REQUIRED = {"version", "url", "algorithm", "digest", "size"}
_DIGEST_LENGTHS = {"sha256": 64, "sha512": 128}


def load_versions(path: Path) -> dict[str, Artifact]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LockfileError(f"cannot read lockfile: {path}") from exc
    if raw.get("schema") != 1:
        raise LockfileError("lockfile schema must be 1")
    artifacts: dict[str, Artifact] = {}
    for name, values in raw.items():
        if name == "schema":
            continue
        if not isinstance(values, dict) or set(values) != _REQUIRED:
            raise LockfileError(f"artifact {name!r} has invalid keys")
        algorithm = values["algorithm"]
        digest = values["digest"]
        url = values["url"]
        size = values["size"]
        version = values["version"]
        if algorithm not in _DIGEST_LENGTHS:
            raise LockfileError(f"artifact {name!r} has unsupported digest")
        if not isinstance(digest, str) or len(digest) != _DIGEST_LENGTHS[algorithm]:
            raise LockfileError(f"artifact {name!r} has invalid digest length")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise LockfileError(f"artifact {name!r} has non-hex digest") from exc
        if not isinstance(url, str) or urlsplit(url).scheme != "https":
            raise LockfileError(f"artifact {name!r} must use HTTPS")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise LockfileError(f"artifact {name!r} has invalid size")
        if not isinstance(version, str) or not version:
            raise LockfileError(f"artifact {name!r} has invalid version")
        artifacts[name] = Artifact(name, version, url, algorithm, digest.lower(), size)
    if not artifacts:
        raise LockfileError("lockfile has no artifacts")
    return artifacts


def verify_file(path: Path, artifact: Artifact) -> bool:
    try:
        if path.stat().st_size != artifact.size:
            return False
        digest = hashlib.new(artifact.algorithm)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == artifact.digest
    except OSError:
        return False
