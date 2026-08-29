import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.approval import GraphicsApprovalError
from msclassic.cli import _install_application, main
from msclassic.doctor import GraphicsReport
from msclassic.input_mode import InputModeStatus
from msclassic.input_diagnostic import InputDiagnosticStatus
from msclassic.paths import AppPaths
from msclassic.profiler import ProfilerStatus
from msclassic.updater import UpdateCheck


REPO = Path(__file__).resolve().parents[1]


def graphics_report(*, passes):
    return GraphicsReport(
        kernel="6.17.0",
        session="x11",
        resolution=(1366, 768),
        drm_nodes=("/dev/dri/renderD128",),
        render_access=True,
        opengl_renderer="virgl" if passes else "llvmpipe",
        vulkan_devices=(),
        selected_device="",
        packages={},
        boot_id="boot-test",
    )


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
        }

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def make_source(self):
        source = self.root / "source"
        for relative in (
            "Maplestory_Classic.exe",
            "UnityPlayer.dll",
            "GameAssembly.dll",
            "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes",
            "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
        return source

    def test_module_usage_error_is_stable_exit_two(self):
        environment = os.environ | self.env | {"PYTHONPATH": str(REPO / "src")}
        result = subprocess.run(
            ["python3", "-m", "msclassic.cli"],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_doctor_stamps_only_passing_boot(self):
        with mock.patch("msclassic.cli.collect_graphics_report", return_value=graphics_report(passes=False)):
            code, output, _ = self.invoke(["doctor", "--json"])
        self.assertEqual(code, 10)
        self.assertFalse((self.root / "state/maplestory-classic/graphics-ok.json").exists())
        self.assertFalse(json.loads(output)["gate_passed"])

        with mock.patch("msclassic.cli.collect_graphics_report", return_value=graphics_report(passes=True)):
            code, _, _ = self.invoke(["doctor", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(
                (self.root / "state/maplestory-classic/graphics-ok.json").read_text()
            ),
            {"schema": 1, "gate_passed": True, "boot_id": "boot-test"},
        )

    def test_handle_url_passes_parsed_request_to_automatic_runner(self):
        with mock.patch("msclassic.cli.run_authenticated", return_value=0) as launched:
            code, _, _ = self.invoke(
                ["handle-url", "nexonplug://?game=2982&passarg=alpha+beta"]
            )

        self.assertEqual(code, 0)
        self.assertEqual(launched.call_args.args[0].arguments, ("alpha", "beta"))

    def test_input_status_prints_safe_json(self):
        status = InputModeStatus("inactive", "No game input profile is active")
        with mock.patch("msclassic.cli.game_input_status", return_value=status):
            code, output, error = self.invoke(["input", "status"])

        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output), status.to_json())

    def test_input_restore_delegates_to_profile_manager(self):
        status = InputModeStatus("inactive", "Game input profile was restored")
        with mock.patch("msclassic.cli.restore_game_input", return_value=status) as restored:
            code, output, error = self.invoke(["input", "restore"])

        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output), status.to_json())
        restored.assert_called_once()

    def test_profile_commands_print_safe_state_and_delegate(self):
        statuses = {
            "start": ProfilerStatus("armed", "The next game launch will capture numeric performance data"),
            "status": ProfilerStatus("capturing", "A numeric performance profile is being captured"),
            "stop": ProfilerStatus("inactive", "Performance profiling is inactive"),
        }
        functions = {
            "start": "arm_profile",
            "status": "profile_status",
            "stop": "stop_profile",
        }

        for command in ("start", "status", "stop"):
            with self.subTest(command=command):
                with mock.patch(
                    f"msclassic.cli.{functions[command]}",
                    return_value=statuses[command],
                ) as invoked:
                    code, output, error = self.invoke(["profile", command])
                self.assertEqual(code, 0)
                self.assertEqual(error, "")
                self.assertEqual(json.loads(output), statuses[command].to_json())
                invoked.assert_called_once()

    def test_input_diagnostic_commands_are_explicit_and_safe(self):
        cases = {
            "diagnose": (
                "arm_input_diagnostic",
                InputDiagnosticStatus("armed", "The next game launch will capture input event categories"),
            ),
            "diagnostic-status": (
                "input_diagnostic_status",
                InputDiagnosticStatus("inactive", "No input diagnostic is armed"),
            ),
            "diagnostic-stop": (
                "stop_input_diagnostic",
                InputDiagnosticStatus("inactive", "No input diagnostic is armed"),
            ),
        }

        for command, (function, status) in cases.items():
            with self.subTest(command=command):
                with mock.patch(f"msclassic.cli.{function}", return_value=status) as invoked:
                    code, output, error = self.invoke(["input", command])
                self.assertEqual(code, 0)
                self.assertEqual(error, "")
                self.assertEqual(json.loads(output), status.to_json())
                invoked.assert_called_once()

    def test_input_summary_prints_no_path_or_free_form_values(self):
        log = self.root / "state/maplestory-classic/input-diagnostic/input-1.bin"
        summary = {
            "schema": 1,
            "records": 2,
            "duration_ns": 10,
            "counts": {"ime_open": 1, "ime_closed": 1},
        }
        with mock.patch("msclassic.cli.summarize_diagnostic", return_value=summary) as invoked:
            code, output, error = self.invoke(["input", "summarize", str(log)])

        self.assertEqual(code, 0)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output), summary)
        self.assertNotIn(str(log), output)
        invoked.assert_called_once()

    def test_handler_failure_uses_fixed_notification_and_redacted_error(self):
        private_uri = "nexonplug://?game=2982&passarg=private-browser-value"
        with mock.patch(
            "msclassic.cli.run_authenticated",
            side_effect=GraphicsApprovalError("graphics launch check failed"),
        ):
            with mock.patch("msclassic.cli.subprocess.run") as notified:
                code, _, error = self.invoke(["handle-url", private_uri])

        self.assertEqual(code, 11)
        self.assertNotIn("private-browser-value", error)
        notification_argv = notified.call_args.args[0]
        self.assertEqual(notification_argv[0], "notify-send")
        self.assertNotIn("private-browser-value", " ".join(notification_argv))

    def test_install_dry_run_and_real_graphics_gate(self):
        source = self.make_source()
        code, output, _ = self.invoke(
            ["install", "--dry-run", "--platform", "lubuntu-24.04", "--source", str(source)]
        )
        self.assertEqual(code, 0)
        self.assertIn("zero mutations", output)

        with mock.patch("msclassic.cli.collect_graphics_report", return_value=graphics_report(passes=False)):
            code, _, _ = self.invoke(
                ["install", "--platform", "lubuntu-24.04", "--source", str(source)]
            )
        self.assertEqual(code, 10)

    def test_download_client_dry_run_requires_no_graphics_or_network(self):
        with mock.patch("msclassic.cli.collect_graphics_report") as graphics:
            with mock.patch("msclassic.cli.installer_main", return_value=0) as installer:
                code, output, _ = self.invoke(
                    ["install", "--dry-run", "--download-client"]
                )

        self.assertEqual(code, 0)
        self.assertEqual(output, "")
        graphics.assert_not_called()
        self.assertEqual(
            installer.call_args.args[0],
            [
                "--dry-run",
                "--platform",
                "lubuntu-24.04",
                "--download-client",
                "--lock",
                str(REPO / "versions.lock"),
            ],
        )

    def test_install_requires_exactly_one_source_or_download_mode(self):
        self.assertEqual(self.invoke(["install"])[0], 2)
        self.assertEqual(
            self.invoke(
                [
                    "install",
                    "--download-client",
                    "--source",
                    str(self.root / "source"),
                ]
            )[0],
            2,
        )

    def test_installed_application_retains_patched_runtime_builder_assets(self):
        paths = AppPaths.from_environment(self.env)
        _install_application(paths)

        installed = paths.data / "app"
        builder = installed / "scripts/build-patched-wine.sh"
        diagnostic_builder = installed / "scripts/build-input-diagnostic-wine.sh"
        patch = installed / "patches/wine-11.10-ntdll-frame-walk-page-fault-guard.patch"
        diagnostic_patch = installed / "patches/wine-11.10-msclassic-input-diagnostic.patch"
        self.assertTrue(builder.is_file())
        self.assertTrue(builder.stat().st_mode & 0o100)
        self.assertTrue(patch.is_file())
        self.assertTrue(diagnostic_builder.is_file())
        self.assertTrue(diagnostic_builder.stat().st_mode & 0o100)
        self.assertTrue(diagnostic_patch.is_file())

    def test_chromium_policy_is_scoped_to_official_ngm_origin(self):
        policy = json.loads(
            (REPO / "platforms/lubuntu-24.04/chromium-policy.json").read_text()
        )
        self.assertEqual(
            policy,
            {
                "AutoLaunchProtocolsFromOrigins": [
                    {
                        "protocol": "ngm",
                        "allowed_origins": [
                            "https://maplestoryclassic.beanfun.com"
                        ],
                    }
                ]
            },
        )

    def test_update_and_stop_require_explicit_mutation_flags(self):
        with mock.patch(
            "msclassic.cli.check_update",
            return_value=UpdateCheck(1, 2, True, "ready"),
        ):
            code, output, _ = self.invoke(["update"])
        self.assertEqual(code, 0)
        self.assertIn('"allowed": true', output)

        with mock.patch("msclassic.cli.stop_prefix") as stopped:
            code, _, _ = self.invoke(["stop"])
            self.assertEqual(code, 2)
            stopped.assert_not_called()
            code, _, _ = self.invoke(["stop", "--yes"])
            self.assertEqual(code, 0)
            stopped.assert_called_once()

    def test_debugger_command_requires_an_available_windows_executable(self):
        code, _, error = self.invoke(
            [
                "debugger",
                "--windows-ce",
                str(self.home / "missing-cheat-engine.exe"),
            ]
        )

        self.assertEqual(code, 11)
        self.assertIn("Windows Cheat Engine executable is unavailable", error)

    def test_trial_lifecycle_writes_redacted_private_state(self):
        begin = [
            "trial",
            "begin",
            "--name",
            "virgl-check",
            "--hypothesis",
            "VirGL provides OpenGL",
            "--variable",
            "opengl_renderer",
            "--before",
            "llvmpipe",
            "--after",
            "virgl",
            "--expected",
            "VirGL appears",
            "--pass-rule",
            "gate_passed=true",
        ]
        with mock.patch(
            "msclassic.cli.collect_graphics_report",
            return_value=graphics_report(passes=True),
        ):
            self.assertEqual(self.invoke(begin)[0], 0)
        self.assertEqual(
            self.invoke(["trial", "observe", "AnyDesk reconnected"])[0],
            0,
        )
        code, output, _ = self.invoke(["trial", "finish", "candidate"])
        self.assertEqual(code, 0)
        manifest = json.loads((Path(output.strip()) / "manifest.json").read_text())
        self.assertEqual(manifest["observations"], ["AnyDesk reconnected"])

    def test_uninstall_retains_client_and_prefix(self):
        client = self.home / "Games/MapleStoryClassic"
        prefix = self.root / "data/maplestory-classic/prefix-wine1110"
        client.mkdir(parents=True)
        prefix.mkdir(parents=True)
        with mock.patch("msclassic.cli.restore_desktop_handler") as restored:
            code, _, _ = self.invoke(["uninstall"])
        self.assertEqual(code, 0)
        restored.assert_called_once()
        self.assertTrue(client.exists())
        self.assertTrue(prefix.exists())


if __name__ == "__main__":
    unittest.main()
