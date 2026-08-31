from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping
from urllib.parse import urlsplit

from .client_download import (
    ClientDownloadError,
    assert_safe_client_tree,
    download_and_promote,
)
from .doctor import GraphicsReport, evaluate_launch_graphics
from .lockfile import Artifact, load_versions, verify_file
from .ngs import inspect_ngs_state
from .paths import AppPaths
from .platforms import PlatformAdapter, read_os_release, select_platform
from .runtime import (
    PATCHED_BUILD_CACHE,
    base_runtime_root,
    base_runtime_valid,
    patched_runtime_build_supported,
    patched_runtime_root,
    patched_runtime_valid,
)


MINIMUM_FREE_BYTES = 2 * 1024**3
INPUT_RUNTIME_HEADROOM_BYTES = 1024**3
REQUIRED_CLIENT_FILES = (
    "Maplestory_Classic.exe",
    "UnityPlayer.dll",
    "GameAssembly.dll",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe",
)
_REPO = Path(__file__).resolve().parents[2]


class InstallerError(ValueError):
    pass


class UnsafeArchiveError(InstallerError):
    pass


@dataclass(frozen=True)
class InstallAction:
    kind: str
    values: tuple[str, ...] = ()
    source: Path | None = None
    destination: Path | None = None
    artifact: Artifact | None = None


@dataclass(frozen=True)
class InstallPlan:
    actions: tuple[InstallAction, ...]
    required_bytes: int


@dataclass(frozen=True)
class InstallResult:
    mutated: bool
    completed: tuple[str, ...]


def package_command_prefix(*, euid: int, sudo_path: str | None) -> tuple[str, ...]:
    if euid == 0:
        return ()
    if sudo_path:
        return (sudo_path,)
    raise InstallerError("package installation requires root or sudo")


def build_install_plan(
    paths: AppPaths,
    artifacts: Mapping[str, Artifact],
    source: Path | None,
    adapter: PlatformAdapter,
    *,
    download_client: bool = False,
) -> InstallPlan:
    if download_client == (source is not None):
        raise InstallerError("choose --source PATH or --download-client")
    unsupported = sorted(set(artifacts) - {"wine", "nxdl"})
    if unsupported:
        raise InstallerError("unsupported locked artifact: " + ", ".join(unsupported))
    source_bytes = 0
    if source is not None:
        source = source.resolve()
        _validate_client(source)
        source_bytes = _tree_size(source)
    elif "nxdl" not in artifacts:
        raise InstallerError("locked nxdl artifact is required for client download")
    required_bytes = source_bytes + sum(item.size * 3 for item in artifacts.values()) + MINIMUM_FREE_BYTES
    if "wine" in artifacts:
        required_bytes += INPUT_RUNTIME_HEADROOM_BYTES
    actions: list[InstallAction] = [InstallAction("install_packages", adapter.package_names)]

    downloads = paths.cache / "downloads"
    for name in sorted(artifacts):
        artifact = artifacts[name]
        filename = Path(urlsplit(artifact.url).path).name
        if not filename or filename in {".", ".."}:
            raise InstallerError(f"artifact {name!r} has no safe download filename")
        cached = downloads / filename
        if cached.exists() and verify_file(cached, artifact):
            actions.append(InstallAction("reuse_artifact", (name,), cached, artifact=artifact))
        else:
            if cached.exists():
                actions.append(InstallAction("quarantine_artifact", (name,), cached, artifact=artifact))
            actions.append(InstallAction("download_artifact", (name,), destination=cached, artifact=artifact))
        if name == "wine":
            runtime_destination = paths.tools / artifact.version
            actions.append(
                InstallAction(
                    "extract_artifact",
                    (name, artifact.version),
                    source=cached,
                    destination=runtime_destination,
                    artifact=artifact,
                )
            )
            actions.append(
                InstallAction(
                    "prepare_base_runtime",
                    (name, artifact.version),
                    source=runtime_destination,
                    destination=base_runtime_root(paths, artifact),
                    artifact=artifact,
                )
            )
            actions.append(
                InstallAction(
                    "prepare_patched_runtime",
                    (name, artifact.version),
                    source=base_runtime_root(paths, artifact),
                    destination=patched_runtime_root(paths, artifact),
                    artifact=artifact,
                )
            )
        elif name == "nxdl":
            actions.append(
                InstallAction(
                    "install_binary",
                    (name, artifact.version),
                    source=cached,
                    destination=paths.tools / f"nxdl-{artifact.version}" / "nxdl",
                    artifact=artifact,
                )
            )

    client_entry_exists = paths.client.exists() or paths.client.is_symlink()
    if download_client and not client_entry_exists:
        actions.append(
            InstallAction(
                "acquire_client",
                destination=paths.client,
                artifact=artifacts["nxdl"],
            )
        )
    elif not client_entry_exists:
        if source is None:
            raise InstallerError("client source is unavailable")
        actions.append(InstallAction("import_client", source=source, destination=paths.client))
    else:
        try:
            _validate_client(paths.client)
        except InstallerError:
            if download_client:
                raise InstallerError("existing client is invalid; refusing to replace it")
            if source is None:
                raise InstallerError("client source is unavailable")
            actions.append(InstallAction("backup_client", source=paths.client))
            actions.append(InstallAction("import_client", source=source, destination=paths.client))
        else:
            if download_client:
                try:
                    assert_safe_client_tree(paths.client)
                except ClientDownloadError as exc:
                    raise InstallerError(
                        "existing client is invalid; refusing to replace it"
                    ) from exc
            actions.append(InstallAction("verify_client", source=paths.client))

    actions.append(InstallAction("initialize_prefix", destination=paths.prefix))
    actions.append(InstallAction("import_registry", destination=paths.prefix))
    actions.append(
        InstallAction(
            "install_ngs",
            source=(
                paths.client
                / "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe"
            ),
            destination=paths.prefix,
        )
    )
    return InstallPlan(tuple(actions), required_bytes)


def execute_install(
    plan: InstallPlan,
    graphics: GraphicsReport,
    dry_run: bool,
    *,
    operation: Callable[[InstallAction], None] | None = None,
) -> InstallResult:
    if dry_run:
        return InstallResult(False, ())
    passed, failures = evaluate_launch_graphics(graphics)
    if not passed:
        raise InstallerError("graphics gate failed: " + "; ".join(failures))
    if operation is None:
        raise InstallerError("an audited installation executor is required")
    completed: list[str] = []
    for action in plan.actions:
        operation(action)
        completed.append(action.kind)
    return InstallResult(bool(completed), tuple(completed))


def perform_install(
    plan: InstallPlan,
    graphics: GraphicsReport,
    paths: AppPaths,
    registry_path: Path,
) -> InstallResult:
    try:
        available = shutil.disk_usage(paths.home).free
    except OSError as exc:
        raise InstallerError("cannot inspect installation free space") from exc
    if available < plan.required_bytes:
        raise InstallerError("insufficient free space for client, runtimes, and rollback headroom")

    def operation(action: InstallAction) -> None:
        _execute_action(action, paths, registry_path)

    return execute_install(plan, graphics, False, operation=operation)


def validate_tar_archive(path: Path) -> None:
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                if member.ischr() or member.isblk() or member.isfifo():
                    raise UnsafeArchiveError("archive contains a device or FIFO")
                member_path = PurePosixPath(member.name)
                if not _path_stays_inside(member_path.parts):
                    raise UnsafeArchiveError("archive member escapes destination")
                if member.issym() or member.islnk():
                    link_path = PurePosixPath(member.linkname)
                    if link_path.is_absolute():
                        raise UnsafeArchiveError("archive link is absolute")
                    combined = (*member_path.parent.parts, *link_path.parts)
                    if not _path_stays_inside(combined):
                        raise UnsafeArchiveError("archive link escapes destination")
    except (tarfile.TarError, OSError) as exc:
        if isinstance(exc, UnsafeArchiveError):
            raise
        raise UnsafeArchiveError("cannot inspect runtime archive") from exc


def _execute_action(action: InstallAction, paths: AppPaths, registry_path: Path) -> None:
    if action.kind in {"install_packages", "reuse_artifact", "verify_client"}:
        return
    if action.kind == "quarantine_artifact":
        if action.source is None:
            raise InstallerError("invalid quarantine action")
        _quarantine(action.source)
        return
    if action.kind == "download_artifact":
        _download_artifact(action)
        return
    if action.kind == "extract_artifact":
        _extract_artifact(action)
        return
    if action.kind == "prepare_base_runtime":
        _prepare_base_runtime(action, paths)
        return
    if action.kind == "prepare_patched_runtime":
        _prepare_patched_runtime(action, paths)
        return
    if action.kind == "install_binary":
        _install_binary(action)
        return
    if action.kind == "acquire_client":
        if action.artifact is None:
            raise InstallerError("invalid client download action")
        try:
            download_and_promote(paths, action.artifact, _validate_client)
        except ClientDownloadError as exc:
            raise InstallerError(str(exc)) from exc
        return
    if action.kind == "backup_client":
        if action.source is None or not action.source.exists():
            raise InstallerError("client backup source is unavailable")
        backup = _timestamped_sibling(action.source, "backup")
        action.source.replace(backup)
        return
    if action.kind == "import_client":
        _import_client(action)
        return
    if action.kind == "initialize_prefix":
        _run_runtime(paths, ["wineboot", "-u"])
        return
    if action.kind == "import_registry":
        if not registry_path.is_file():
            raise InstallerError("prefix registry file is unavailable")
        _run_runtime(paths, ["regedit", "/S", str(registry_path.resolve())])
        return
    if action.kind == "install_ngs":
        if action.source is None:
            raise InstallerError("invalid NGS installation action")
        _install_ngs_service(paths, action.source)
        return
    raise InstallerError(f"unsupported install action: {action.kind}")


def _download_artifact(action: InstallAction) -> None:
    artifact = action.artifact
    destination = action.destination
    if artifact is None or destination is None:
        raise InstallerError("invalid download action")
    curl = shutil.which("curl")
    if curl is None:
        raise InstallerError("curl is required for locked runtime download")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + f".part-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        completed = subprocess.run(
            [curl, "--fail", "--location", "--proto", "=https", "--output", str(temporary), artifact.url],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60 * 60,
            check=False,
        )
        if completed.returncode != 0:
            raise InstallerError(f"download failed for locked artifact {artifact.name}")
        if not verify_file(temporary, artifact):
            _quarantine(temporary)
            raise InstallerError(f"checksum failed for locked artifact {artifact.name}")
        temporary.chmod(0o600)
        temporary.replace(destination)
    except (OSError, subprocess.TimeoutExpired) as exc:
        temporary.unlink(missing_ok=True)
        raise InstallerError(f"download failed for locked artifact {artifact.name}") from exc


def _extract_artifact(action: InstallAction) -> None:
    archive = action.source
    destination = action.destination
    artifact = action.artifact
    if archive is None or destination is None or artifact is None or not verify_file(archive, artifact):
        raise InstallerError("runtime archive is unavailable or failed verification")
    if _extraction_valid(destination, artifact):
        return
    if destination.exists():
        _quarantine(destination)
    validate_tar_archive(archive)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        with tarfile.open(archive, "r:*") as bundle:
            bundle.extractall(temporary, filter="data")
        children = list(temporary.iterdir())
        if len(children) == 1 and children[0].is_dir():
            children[0].replace(destination)
            temporary.rmdir()
        else:
            temporary.replace(destination)
        _make_user_writable(destination)
        stamp = destination / ".msclassic-artifact.json"
        stamp.write_text(
            json.dumps(
                {"schema": 1, "name": artifact.name, "version": artifact.version, "digest": artifact.digest},
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
        )
        stamp.chmod(0o600)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _install_binary(action: InstallAction) -> None:
    source = action.source
    destination = action.destination
    artifact = action.artifact
    if source is None or destination is None or artifact is None or not verify_file(source, artifact):
        raise InstallerError("locked binary is unavailable or failed verification")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    shutil.copyfile(source, temporary)
    temporary.chmod(0o700)
    if not verify_file(temporary, artifact):
        temporary.unlink(missing_ok=True)
        raise InstallerError("installed binary failed verification")
    temporary.replace(destination)


def _prepare_base_runtime(action: InstallAction, paths: AppPaths) -> None:
    artifact = action.artifact
    source = action.source
    destination = action.destination
    if artifact is None or artifact.name != "wine" or source is None or destination is None:
        raise InstallerError("invalid patched Wine runtime action")
    if base_runtime_valid(paths, artifact):
        return
    expected_source = paths.tools / artifact.version
    expected_destination = base_runtime_root(paths, artifact)
    try:
        paths_match = (
            source.resolve() == expected_source.resolve()
            and destination.resolve() == expected_destination.resolve()
        )
    except OSError as exc:
        raise InstallerError("patched Wine runtime paths are unavailable") from exc
    if not paths_match or not _extraction_valid(source, artifact):
        raise InstallerError("locked base Wine runtime is unavailable")
    if destination.exists():
        raise InstallerError("invalid patched Wine runtime already exists")
    if not patched_runtime_build_supported(paths):
        raise InstallerError("patched Wine v1 requires the validated /home/ubuntu profile")
    builder = _REPO / "scripts/build-patched-wine.sh"
    if not builder.is_file() or not os.access(builder, os.X_OK):
        raise InstallerError("patched Wine runtime builder is unavailable")
    try:
        completed = subprocess.run(
            [
                str(builder),
                "--base-runtime",
                str(source),
                "--output",
                str(destination),
                "--cache",
                str(PATCHED_BUILD_CACHE),
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            timeout=45 * 60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallerError("patched Wine runtime build failed") from exc
    if completed.returncode != 0 or not base_runtime_valid(paths, artifact):
        raise InstallerError("patched Wine runtime build failed verification")


def _prepare_patched_runtime(action: InstallAction, paths: AppPaths) -> None:
    artifact = action.artifact
    if artifact is None or artifact.name != "wine":
        raise InstallerError("invalid input runtime action")
    source = base_runtime_root(paths, artifact)
    destination = patched_runtime_root(paths, artifact)
    if action.source != source or action.destination != destination:
        raise InstallerError("invalid input runtime paths")
    if patched_runtime_valid(paths, artifact):
        return
    if not base_runtime_valid(paths, artifact):
        raise InstallerError("verified base Wine runtime is required")
    if destination.exists():
        raise InstallerError("invalid input runtime already exists; refusing to overwrite it")
    if not patched_runtime_build_supported(paths):
        raise InstallerError("input Wine build requires the validated /home/ubuntu profile")
    builder = _REPO / "scripts/build-input-wine.sh"
    if not builder.is_file() or not os.access(builder, os.X_OK):
        raise InstallerError("input Wine runtime builder is unavailable")
    try:
        completed = subprocess.run(
            [str(builder), "--base-runtime", str(source), "--output", str(destination),
             "--cache", str(PATCHED_BUILD_CACHE)],
            shell=False, stdin=subprocess.DEVNULL, timeout=45 * 60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallerError("input Wine runtime build failed") from exc
    if completed.returncode != 0 or not patched_runtime_valid(paths, artifact):
        raise InstallerError("input Wine runtime build failed verification")


def _import_client(action: InstallAction) -> None:
    source = action.source
    destination = action.destination
    if source is None or destination is None:
        raise InstallerError("invalid client import action")
    _validate_client(source)
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".MapleStoryClassic-", dir=destination.parent))
    try:
        rsync = shutil.which("rsync")
        if rsync is None:
            raise InstallerError("rsync is required to import the read-only client")
        completed = subprocess.run(
            [rsync, "--archive", "--exclude=.DS_Store", f"{source}/", f"{temporary}/"],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30 * 60,
            check=False,
        )
        if completed.returncode != 0:
            raise InstallerError("client import failed")
        _validate_client(temporary)
        _make_user_writable(temporary)
        temporary.replace(destination)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _run_runtime(paths: AppPaths, arguments: list[str]) -> None:
    artifact = load_versions(_REPO / "versions.lock")["wine"]
    tools = paths.tools.resolve()
    wine_root = patched_runtime_root(paths, artifact).resolve()
    if not wine_root.is_relative_to(tools) or not patched_runtime_valid(paths, artifact):
        raise InstallerError("pinned Wine runtime is unavailable")
    if not arguments or arguments[0] not in {"wineboot", "regedit"}:
        raise InstallerError("unsupported Wine prefix command")
    command = wine_root / "bin" / arguments[0]
    if not command.is_file() or not os.access(command, os.X_OK):
        raise InstallerError("pinned Wine prefix tool is unavailable")
    paths.prefix.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment = {
        "HOME": str(paths.home),
        "PATH": f"{wine_root / 'bin'}:/usr/bin:/bin",
        "WINEPREFIX": str(paths.prefix),
        "WINEDEBUG": "-all",
        "WINEDLLOVERRIDES": "mscoree,mshtml=",
        "LANG": "zh_TW.UTF-8",
        "LC_ALL": "zh_TW.UTF-8",
    }
    timeout = 60 if arguments[0] == "wineboot" else 10 * 60
    try:
        completed = subprocess.run(
            [str(command), *arguments[1:]],
            shell=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if arguments[0] != "wineboot":
            raise InstallerError("pinned Wine prefix initialization timed out") from exc
        _stop_runtime_server(wine_root, environment)
        if _prefix_initialized(paths.prefix):
            return
        raise InstallerError("Wine prefix initialization timed out before completion") from exc
    except OSError as exc:
        raise InstallerError("pinned Wine prefix initialization failed") from exc
    if completed.returncode != 0:
        raise InstallerError("pinned Wine prefix initialization failed")
    if arguments[0] == "wineboot":
        _stop_runtime_server(wine_root, environment)
        if not _prefix_initialized(paths.prefix):
            raise InstallerError(
                "Wine prefix initialization completed without persistent services"
            )


def _install_ngs_service(paths: AppPaths, executable: Path) -> None:
    expected = (
        paths.client
        / "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe"
    )
    try:
        matches_expected = executable.resolve() == expected.resolve()
    except OSError as exc:
        raise InstallerError("vendor NGS installer is unavailable") from exc
    if not matches_expected or not executable.is_file():
        raise InstallerError("vendor NGS installer is unavailable")
    if not _prefix_initialized(paths.prefix):
        raise InstallerError("Wine prefix service initialization is incomplete")

    artifact = load_versions(_REPO / "versions.lock")["wine"]
    tools = paths.tools.resolve()
    wine_root = patched_runtime_root(paths, artifact).resolve()
    if not wine_root.is_relative_to(tools) or not patched_runtime_valid(paths, artifact):
        raise InstallerError("pinned Wine runtime is unavailable")
    wine = wine_root / "bin/wine"
    if not wine.is_file() or not os.access(wine, os.X_OK):
        raise InstallerError("pinned Wine runtime is unavailable")
    environment = {
        "HOME": str(paths.home),
        "PATH": f"{wine_root / 'bin'}:/usr/bin:/bin",
        "WINEPREFIX": str(paths.prefix),
        "WINEDEBUG": "-all",
        "WINEDLLOVERRIDES": "mscoree,mshtml=",
        "LANG": "zh_TW.UTF-8",
        "LC_ALL": "zh_TW.UTF-8",
    }
    try:
        completed = subprocess.run(
            [str(wine), str(executable), "-install"],
            cwd=executable.parent,
            shell=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallerError("vendor NGS service installation failed") from exc
    if completed.returncode != 0:
        raise InstallerError("vendor NGS service installation failed")
    _stop_runtime_server(wine_root, environment)
    if not inspect_ngs_state(paths).complete:
        raise InstallerError("vendor NGS service installation is incomplete")


def _stop_runtime_server(wine_root: Path, environment: dict[str, str]) -> None:
    wineserver = wine_root / "bin/wineserver"
    for argument in ("-k", "-w"):
        try:
            completed = subprocess.run(
                [str(wineserver), argument],
                shell=False,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallerError("dedicated Wine prefix did not stop cleanly") from exc
        if completed.returncode != 0:
            raise InstallerError("dedicated Wine prefix did not stop cleanly")


def _prefix_initialized(prefix: Path) -> bool:
    system_registry = prefix / "system.reg"
    if not (
        system_registry.is_file()
        and (prefix / "user.reg").is_file()
        and (prefix / "drive_c/windows/system32").is_dir()
    ):
        return False
    try:
        registry = system_registry.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    required_services = (
        "[System\\\\ControlSet001\\\\Services\\\\PlugPlay]",
        "[System\\\\ControlSet001\\\\Services\\\\RpcSs]",
    )
    return all(service in registry for service in required_services)


def _make_user_writable(root: Path) -> None:
    for directory, subdirectories, filenames in os.walk(root):
        base = Path(directory)
        base.chmod(base.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        for name in subdirectories:
            item = base / name
            item.chmod(item.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        for name in filenames:
            item = base / name
            item.chmod(item.stat().st_mode | stat.S_IWUSR)


def _quarantine(path: Path) -> Path:
    if not path.exists():
        return path
    destination = _timestamped_sibling(path, "rejected")
    path.replace(destination)
    return destination


def _timestamped_sibling(path: Path, label: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.{label}-{stamp}")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{label}-{stamp}-{suffix}")
        suffix += 1
    return candidate


def _extraction_valid(destination: Path, artifact: Artifact) -> bool:
    required = {
        "wine": ("bin/wine", "bin/wineserver", "bin/wineboot", "bin/regedit"),
    }.get(artifact.name, ())
    stamp = destination / ".msclassic-artifact.json"
    try:
        value = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return value == {
        "schema": 1,
        "name": artifact.name,
        "version": artifact.version,
        "digest": artifact.digest,
    } and all((destination / relative).is_file() for relative in required)


def _path_stays_inside(parts: tuple[str, ...]) -> bool:
    depth = 0
    for part in parts:
        if part in {"", "."}:
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return False
        else:
            depth += 1
    return bool(parts) and not PurePosixPath(*parts).is_absolute()


def _validate_client(root: Path) -> None:
    if not root.is_dir():
        raise InstallerError("client source is not a directory")
    missing = [relative for relative in REQUIRED_CLIENT_FILES if not (root / relative).is_file()]
    if missing:
        raise InstallerError("client source is incomplete")


def _tree_size(root: Path) -> int:
    total = 0
    try:
        for directory, _, filenames in os.walk(root):
            base = Path(directory)
            for filename in filenames:
                item = base / filename
                if item.is_symlink():
                    raise InstallerError("client tree cannot contain symlinks")
                total += item.stat().st_size
    except OSError as exc:
        raise InstallerError("cannot inspect client source") from exc
    return total


def _format_bytes(value: int) -> str:
    return f"{value} bytes ({value / 1024**3:.2f} GiB)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan the MapleStory Classic guest installation")
    parser.add_argument("--dry-run", action="store_true", required=True)
    client_mode = parser.add_mutually_exclusive_group(required=True)
    client_mode.add_argument("--source", type=Path)
    client_mode.add_argument("--download-client", action="store_true")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--platform")
    args = parser.parse_args(argv)

    from .lockfile import load_versions

    paths = AppPaths.from_environment(os.environ)
    artifacts = load_versions(args.lock)
    adapter = select_platform(args.platform, read_os_release())
    plan = build_install_plan(
        paths,
        artifacts,
        args.source,
        adapter,
        download_client=args.download_client,
    )

    print("DRY RUN: zero mutations")
    if args.source is not None:
        source_bytes = _tree_size(args.source.resolve())
        print(f"Client source: {args.source.resolve()}")
        print(f"Client size: {_format_bytes(source_bytes)}")
    else:
        print("Client source: public nxdl manifest (size checked during real install)")
    print(f"Required free space: {_format_bytes(plan.required_bytes)}")
    print(f"Platform: {adapter.id}")
    print("Packages: " + " ".join(adapter.package_names))
    print("Locked artifacts:")
    for name in sorted(artifacts):
        artifact = artifacts[name]
        print(f"  {name}: {artifact.version} ({artifact.algorithm}:{artifact.digest})")
    print("Planned actions:")
    for action in plan.actions:
        suffix = " " + " ".join(action.values) if action.values else ""
        print(f"  {action.kind}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
