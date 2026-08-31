from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .audit import DriftError, TrialError, TrialRecorder, TrialSpec, compare_reference
from .approval import (
    GraphicsApprovalError,
    invalidate_graphics_approval,
    write_graphics_approval,
)
from .doctor import collect_graphics_report, evaluate_launch_graphics
from .debugger import DebuggerError, run_windows_ce
from .installer import InstallerError, build_install_plan, main as installer_main, perform_install
from .input_mode import InputModeError, game_input_status, restore_game_input
from .input_diagnostic import (
    arm_input_diagnostic,
    input_diagnostic_directory,
    input_diagnostic_status,
    stop_input_diagnostic,
    summarize_diagnostic,
)
from .lockfile import LockfileError, load_versions
from .paths import AppPaths
from .platforms import UnsupportedPlatformError, read_os_release, select_platform
from .profiler import arm_profile, profile_status, stop_profile
from .protocol import ProtocolError, parse_launch_uri
from .redaction import UnsafeExportError, assert_export_safe
from .runner import (
    ActiveSessionError,
    RunnerError,
    install_desktop_handler,
    restore_desktop_handler,
    run_authenticated,
)
from .updater import UpdaterError, apply_update, check_update, stop_prefix


EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_GRAPHICS = 10
EXIT_CONFIGURATION = 11
EXIT_CHECKSUM = 12
EXIT_UNSAFE_INPUT = 13
EXIT_ACTIVE_SESSION = 14
EXIT_DRIFT = 15
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
    except DriftError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DRIFT
    except LockfileError:
        if args.command == "handle-url":
            _fixed_launch_failure(args.command)
        else:
            print("Pinned runtime metadata is invalid.", file=sys.stderr)
        return EXIT_CHECKSUM
    except (
        GraphicsApprovalError,
        DebuggerError,
        InputModeError,
        InstallerError,
        RunnerError,
        TrialError,
        UnsupportedPlatformError,
        UpdaterError,
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
            installer_arguments = [
                "--dry-run",
                "--platform",
                adapter.id,
            ]
            if args.command == "install" and args.download_client:
                installer_arguments.append("--download-client")
            else:
                installer_arguments.extend(["--source", str(args.source)])
            installer_arguments.extend(["--lock", str(REPO / "versions.lock")])
            return installer_main(
                installer_arguments
            )
        report = collect_graphics_report(paths)
        passed, failures = evaluate_launch_graphics(report)
        if not passed:
            invalidate_graphics_approval(paths)
            print("Graphics gate failed: " + "; ".join(failures), file=sys.stderr)
            return EXIT_GRAPHICS
        artifacts = load_versions(REPO / "versions.lock")
        plan = build_install_plan(
            paths,
            artifacts,
            args.source,
            adapter,
            download_client=args.download_client,
        )
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

    if args.command == "input":
        if args.input_command == "status":
            payload = game_input_status(paths, os.environ).to_json()
        elif args.input_command == "restore":
            payload = restore_game_input(paths, os.environ).to_json()
        elif args.input_command == "diagnose":
            artifact = load_versions(REPO / "versions.lock")["wine"]
            payload = arm_input_diagnostic(paths, artifact, persistent=args.persistent).to_json()
        elif args.input_command == "diagnostic-status":
            payload = input_diagnostic_status(paths).to_json()
        elif args.input_command == "diagnostic-stop":
            payload = stop_input_diagnostic(paths).to_json()
        elif args.input_command == "summarize":
            payload = summarize_diagnostic(
                args.path,
                input_diagnostic_directory(paths),
            )
        else:
            raise ValueError("unsupported input command")
        assert_export_safe(payload)
        print(json.dumps(payload, sort_keys=True))
        return EXIT_SUCCESS

    if args.command == "profile":
        if args.profile_command == "start":
            payload = arm_profile(paths).to_json()
        elif args.profile_command == "status":
            payload = profile_status(paths).to_json()
        elif args.profile_command == "stop":
            payload = stop_profile(paths).to_json()
        else:
            raise ValueError("unsupported profile command")
        assert_export_safe(payload)
        print(json.dumps(payload, sort_keys=True))
        return EXIT_SUCCESS

    if args.command == "update":
        artifact = load_versions(REPO / "versions.lock")["nxdl"]
        if args.apply:
            result = apply_update(paths, artifact)
            return EXIT_SUCCESS if result == 0 else EXIT_EXTERNAL_COMMAND
        print(json.dumps(asdict(check_update(paths, artifact)), sort_keys=True))
        return EXIT_SUCCESS

    if args.command == "stop":
        if not args.yes:
            print(
                "Use --yes to stop only the dedicated MapleStory Classic prefix.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        result = stop_prefix(paths, confirmed=True)
        return (
            EXIT_SUCCESS
            if not isinstance(result, int) or result == 0
            else EXIT_EXTERNAL_COMMAND
        )

    if args.command == "debugger":
        result = run_windows_ce(args.windows_ce, paths)
        return EXIT_SUCCESS if result == 0 else EXIT_EXTERNAL_COMMAND

    if args.command == "trial":
        return _trial(args, paths)

    if args.command == "reproduce":
        return _reproduce(args, paths)

    if args.command == "uninstall":
        restore_desktop_handler(paths)
        (paths.home / ".local/bin/msclassic").unlink(missing_ok=True)
        print("Desktop integration removed; the game client and Wine prefix were retained.")
        return EXIT_SUCCESS

    raise ValueError("unsupported command")


def _trial(args: argparse.Namespace, paths: AppPaths) -> int:
    active = paths.state / "active-trial.json"
    if args.trial_command == "begin":
        if active.exists():
            raise TrialError("a trial is already active")
        spec = TrialSpec(
            args.name,
            args.hypothesis,
            args.variable,
            args.before,
            args.after,
            args.expected,
            args.pass_rule,
        )
        payload = {
            "schema": 1,
            "started_at": datetime.now().astimezone().isoformat(),
            "trial": asdict(spec),
            "baseline": collect_graphics_report(paths).to_json(),
            "observations": [],
        }
        _write_private_json(active, payload)
        print("Trial started.")
        return EXIT_SUCCESS
    if args.trial_command == "export":
        return _export_trial(args.run_id, paths)
    payload = _read_active_trial(active)
    if args.trial_command == "observe":
        assert_export_safe(args.text)
        payload["observations"].append(args.text)
        _write_private_json(active, payload)
        print("Observation recorded.")
        return EXIT_SUCCESS
    if args.trial_command == "finish":
        spec = TrialSpec(**payload["trial"])
        recorder = TrialRecorder(paths.runs).begin(spec, payload["baseline"])
        recorder.started_at = payload["started_at"]
        for observation in payload["observations"]:
            recorder.observe(observation)
        run = recorder.finish(args.disposition)
        active.unlink()
        print(run)
        return EXIT_SUCCESS
    raise TrialError("unsupported trial command")


def _export_trial(run_id: str, paths: AppPaths) -> int:
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z0-9][a-z0-9-]{0,63}", run_id):
        raise TrialError("run id is invalid")
    source = paths.runs / run_id
    manifest_path = source / "manifest.json"
    report_path = source / "report.md"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = report_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        raise TrialError("run is unavailable") from exc
    assert_export_safe(manifest)
    assert_export_safe(report)
    destination = REPO / "reports/candidates" / run_id
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copyfile(manifest_path, destination / "manifest.json")
    shutil.copyfile(report_path, destination / "report.md")
    for item in destination.iterdir():
        item.chmod(0o600)
    print(destination)
    return EXIT_SUCCESS


def _reproduce(args: argparse.Namespace, paths: AppPaths) -> int:
    artifacts = load_versions(REPO / "versions.lock")
    profile = REPO / "platforms/proxmox/pve-virgl.toml"
    report = collect_graphics_report(paths)
    current = {
        "artifact_versions": {
            name: item.version for name, item in sorted(artifacts.items())
        },
        "artifact_digests": {
            name: item.digest for name, item in sorted(artifacts.items())
        },
        "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "kernel": report.kernel,
        "renderer": report.opengl_renderer,
    }
    reference_path = REPO / "reports/reference/fingerprint.json"
    drift: list[str] = []
    if reference_path.exists():
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        assert_export_safe(reference)
        drift = compare_reference(reference, current, args.accept_drift)
    spec = TrialSpec(
        "reproduce",
        "Locked profile reproduces the accepted graphics and runtime inputs",
        "reference_drift",
        "accepted-reference" if reference_path.exists() else "no-reference",
        "candidate",
        "doctor and locked-input comparison complete",
        "no unexplained drift and graphics gate passes",
    )
    baseline = {"fingerprint": current, "drift": drift, "graphics": report.to_json()}
    run = TrialRecorder(paths.runs).begin(spec, baseline).finish("candidate")
    print(run)
    return EXIT_SUCCESS if evaluate_launch_graphics(report)[0] else EXIT_GRAPHICS


def _read_active_trial(path: Path) -> dict[str, object]:
    try:
        if path.stat().st_size > 65_536:
            raise TrialError("active trial state is invalid")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrialError("no active trial") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise TrialError("active trial state is invalid")
    if not isinstance(value.get("observations"), list):
        raise TrialError("active trial state is invalid")
    assert_export_safe(value)
    return value


def _write_private_json(path: Path, value: object) -> None:
    assert_export_safe(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


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
    (temporary_root / "scripts").mkdir(mode=0o700)
    shutil.copy2(
        REPO / "scripts/build-patched-wine.sh",
        temporary_root / "scripts/build-patched-wine.sh",
    )
    shutil.copy2(
        REPO / "scripts/build-input-wine.sh",
        temporary_root / "scripts/build-input-wine.sh",
    )
    shutil.copytree(REPO / "patches", temporary_root / "patches")
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
    client_mode = install.add_mutually_exclusive_group(required=True)
    client_mode.add_argument("--source", type=Path)
    client_mode.add_argument("--download-client", action="store_true")
    handler = subcommands.add_parser("handle-url")
    handler.add_argument("uri")
    input_command = subcommands.add_parser("input")
    input_subcommands = input_command.add_subparsers(dest="input_command", required=True)
    input_subcommands.add_parser("status")
    input_subcommands.add_parser("restore")
    input_diagnose = input_subcommands.add_parser("diagnose")
    input_diagnose.add_argument(
        "--persistent", action="store_true",
        help="capture private input diagnostics on each launch until diagnostic-stop",
    )
    input_subcommands.add_parser("diagnostic-status")
    input_subcommands.add_parser("diagnostic-stop")
    input_summary = input_subcommands.add_parser("summarize")
    input_summary.add_argument("path", type=Path)
    profile = subcommands.add_parser("profile")
    profile_subcommands = profile.add_subparsers(dest="profile_command", required=True)
    profile_subcommands.add_parser("start")
    profile_subcommands.add_parser("status")
    profile_subcommands.add_parser("stop")
    stop = subcommands.add_parser("stop")
    stop.add_argument("--yes", action="store_true")
    debugger = subcommands.add_parser("debugger")
    debugger.add_argument("--windows-ce", type=Path, required=True)
    update = subcommands.add_parser("update")
    update.add_argument("--apply", action="store_true")
    trial = subcommands.add_parser("trial")
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    begin = trial_commands.add_parser("begin")
    for flag in (
        "name",
        "hypothesis",
        "variable",
        "before",
        "after",
        "expected",
        "pass-rule",
    ):
        begin.add_argument(f"--{flag}", required=True, dest=flag.replace("-", "_"))
    observe = trial_commands.add_parser("observe")
    observe.add_argument("text")
    finish = trial_commands.add_parser("finish")
    finish.add_argument(
        "disposition",
        choices=("rejected", "inconclusive", "candidate", "reference"),
    )
    export = trial_commands.add_parser("export")
    export.add_argument("run_id")
    reproduce = subcommands.add_parser("reproduce")
    reproduce.add_argument("--accept-drift", action="store_true")
    subcommands.add_parser("uninstall")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
