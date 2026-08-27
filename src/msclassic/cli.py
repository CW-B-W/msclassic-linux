from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .approval import (
    GraphicsApprovalError,
    invalidate_graphics_approval,
    write_graphics_approval,
)
from .doctor import collect_graphics_report, evaluate_launch_graphics
from .installer import InstallerError, build_install_plan, main as installer_main, perform_install
from .lockfile import LockfileError, load_versions
from .paths import AppPaths
from .platforms import UnsupportedPlatformError, read_os_release, select_platform
from .protocol import ProtocolError, parse_launch_uri
from .redaction import UnsafeExportError
from .runner import (
    ActiveSessionError,
    RunnerError,
    install_desktop_handler,
    restore_desktop_handler,
    run_authenticated,
)


EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_GRAPHICS = 10
EXIT_CONFIGURATION = 11
EXIT_CHECKSUM = 12
EXIT_UNSAFE_INPUT = 13
EXIT_ACTIVE_SESSION = 14
EXIT_EXTERNAL_COMMAND = 20

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    paths = AppPaths.from_environment(os.environ)
    try:
        return _dispatch(args, paths)
    except ActiveSessionError:
        _fixed_launch_failure(args.command)
        return EXIT_ACTIVE_SESSION
    except (ProtocolError, UnsafeExportError):
        _fixed_launch_failure(args.command)
        return EXIT_UNSAFE_INPUT
    except LockfileError:
        if args.command == "handle-url":
            _fixed_launch_failure(args.command)
        else:
            print("Pinned runtime metadata is invalid.", file=sys.stderr)
        return EXIT_CHECKSUM
    except (
        GraphicsApprovalError,
        InstallerError,
        RunnerError,
        UnsupportedPlatformError,
        OSError,
        ValueError,
    ) as exc:
        if args.command == "handle-url":
            _fixed_launch_failure(args.command)
        else:
            print(str(exc), file=sys.stderr)
        return EXIT_CONFIGURATION


def entrypoint() -> None:
    raise SystemExit(main())


def _dispatch(args: argparse.Namespace, paths: AppPaths) -> int:
    if args.command == "doctor":
        report = collect_graphics_report(paths)
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print("PASS" if payload["gate_passed"] else "FAIL")
            for failure in payload["failures"]:
                print(f"- {failure}")
        if payload["gate_passed"]:
            if not args.preflight:
                write_graphics_approval(paths, report)
            return EXIT_SUCCESS
        invalidate_graphics_approval(paths)
        return EXIT_GRAPHICS

    if args.command in {"plan", "install"}:
        adapter = select_platform(args.platform, read_os_release())
        if args.command == "plan" or args.dry_run:
            return installer_main(
                [
                    "--dry-run",
                    "--platform",
                    adapter.id,
                    "--source",
                    str(args.source),
                    "--lock",
                    str(REPO / "versions.lock"),
                ]
            )
        report = collect_graphics_report(paths)
        passed, failures = evaluate_launch_graphics(report)
        if not passed:
            invalidate_graphics_approval(paths)
            print("Graphics gate failed: " + "; ".join(failures), file=sys.stderr)
            return EXIT_GRAPHICS
        artifacts = load_versions(REPO / "versions.lock")
        plan = build_install_plan(paths, artifacts, args.source, adapter)
        perform_install(
            plan,
            report,
            paths,
            REPO / "platforms/lubuntu-24.04/maplestory-classic.reg",
        )
        write_graphics_approval(paths, report)
        _install_application(paths)
        install_desktop_handler(paths)
        print(f"Installed MapleStory Classic runtime with {len(plan.actions)} audited actions.")
        return EXIT_SUCCESS

    if args.command == "handle-url":
        request = parse_launch_uri(args.uri)
        result = run_authenticated(request, paths)
        return EXIT_SUCCESS if result == 0 else EXIT_EXTERNAL_COMMAND

    if args.command == "uninstall":
        restore_desktop_handler(paths)
        (paths.home / ".local/bin/msclassic").unlink(missing_ok=True)
        print("Desktop integration removed; the game client and Wine prefix were retained.")
        return EXIT_SUCCESS

    raise ValueError("unsupported command")


def _fixed_launch_failure(command: str) -> None:
    if command != "handle-url":
        print("MapleStory Classic is already active.", file=sys.stderr)
        return
    message = "The authenticated launch could not be started. Run msclassic doctor for details."
    print(message, file=sys.stderr)
    try:
        subprocess.run(
            ["notify-send", "MapleStory Classic", message],
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _install_application(paths: AppPaths) -> None:
    installed_root = paths.data / "app"
    temporary_root = paths.data / ".app.tmp"
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    (temporary_root / "src").mkdir(mode=0o700, parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(REPO / "src/msclassic", temporary_root / "src/msclassic", ignore=ignore)
    shutil.copytree(REPO / "desktop", temporary_root / "desktop")
    shutil.copytree(REPO / "platforms", temporary_root / "platforms", ignore=ignore)
    shutil.copyfile(REPO / "versions.lock", temporary_root / "versions.lock")
    if installed_root.exists():
        backup = paths.data / ".app.previous"
        if backup.exists():
            shutil.rmtree(backup)
        installed_root.replace(backup)
    temporary_root.replace(installed_root)

    binary_directory = paths.home / ".local/bin"
    binary_directory.mkdir(mode=0o755, parents=True, exist_ok=True)
    wrapper = binary_directory / "msclassic"
    if "'" in str(installed_root):
        raise InstallerError("installed application path contains unsupported characters")
    content = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"export PYTHONPATH='{installed_root / 'src'}'\n"
        "exec python3 -m msclassic.cli \"$@\"\n"
    )
    temporary = wrapper.with_name(wrapper.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o700)
    temporary.replace(wrapper)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msclassic")
    subcommands = parser.add_subparsers(dest="command", required=True)
    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--preflight", action="store_true")
    plan = subcommands.add_parser("plan")
    plan.add_argument("--platform", default="lubuntu-24.04")
    plan.add_argument("--source", type=Path, default=Path("/media/ubuntu/MapleStoryClassic"))
    install = subcommands.add_parser("install")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--platform", default="lubuntu-24.04")
    install.add_argument("--source", type=Path, default=Path("/media/ubuntu/MapleStoryClassic"))
    handler = subcommands.add_parser("handle-url")
    handler.add_argument("uri")
    subcommands.add_parser("uninstall")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
