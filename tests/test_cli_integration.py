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
from msclassic.cli import main
from msclassic.doctor import GraphicsReport
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
