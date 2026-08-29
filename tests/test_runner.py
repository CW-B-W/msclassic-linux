import fcntl
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.doctor import GraphicsReport
from msclassic.input_mode import InputModeStatus
from msclassic.lockfile import load_versions
from msclassic.paths import AppPaths
from msclassic.protocol import LaunchRequest
from msclassic.runner import (
    ActiveSessionError,
    RunnerError,
    build_wine_command,
    install_desktop_handler,
    restore_desktop_handler,
    run_authenticated,
)
from msclassic.runtime import patched_runtime_root


REPO = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})
        artifact = load_versions(REPO / "versions.lock")["wine"]
        self.wine_root = patched_runtime_root(self.paths, artifact)
        self.wine = self.wine_root / "bin/wine"
        self.wine.parent.mkdir(parents=True)
        shutil.copy2(REPO / "tests/fixtures/fake-wine", self.wine)
        self.wine.chmod(0o700)
        wineserver = self.wine_root / "bin/wineserver"
        wineserver.write_bytes(b"server")
        wineserver.chmod(0o700)
        (self.wine_root / ".msclassic-artifact.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": artifact.name,
                    "version": artifact.version,
                    "digest": artifact.digest,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        executable = self.paths.client / "Maplestory_Classic.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"MZ")
        executable.chmod(0o600)
        self.paths.prefix.mkdir(parents=True)
        (self.paths.prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\NGS] 1\n",
            encoding="utf-8",
        )
        broker = (
            self.paths.prefix
            / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
        )
        broker.parent.mkdir(parents=True)
        broker.write_bytes(b"MZ")
        self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        self.paths.state.mkdir(parents=True)
        self.write_approval(self.boot_id)
        self.runtime_validation = mock.patch(
            "msclassic.runner.patched_runtime_valid", return_value=True
        )
        self.runtime_validation.start()
        self.input_patches = [
            mock.patch(
                "msclassic.runner.activate_game_input",
                return_value=InputModeStatus(
                    "unavailable", "Lubuntu X11 input profile is unavailable"
                ),
            ),
            mock.patch(
                "msclassic.runner.restore_game_input",
                return_value=InputModeStatus(
                    "inactive", "No game input profile is active"
                ),
            ),
        ]
        for patch in self.input_patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.input_patches):
            patch.stop()
        self.runtime_validation.stop()
        self.temp.cleanup()

    def write_approval(self, boot_id):
        (self.paths.state / "graphics-ok.json").write_text(
            json.dumps({"schema": 1, "gate_passed": True, "boot_id": boot_id}),
            encoding="utf-8",
        )

    def passing_report(self):
        return GraphicsReport(
            kernel="6.17.0",
            session="x11",
            resolution=(1366, 768),
            drm_nodes=("/dev/dri/renderD128",),
            render_access=True,
            opengl_renderer="virgl",
            vulkan_devices=(),
            selected_device="",
            packages={},
            boot_id=self.boot_id,
        )

    def test_builds_exact_argv_and_minimal_environment(self):
        request = LaunchRequest("2982", "TW", ("alpha", "beta gamma"))
        inherited = {
            "DISPLAY": ":0",
            "XAUTHORITY": "/run/user/1000/xauth",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_CONFIG_HOME": "/home/example/.config",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "XDG_SESSION_TYPE": "x11",
            "PULSE_SERVER": "unix:/run/pulse/native",
            "PIPEWIRE_REMOTE": "pipewire-0",
            "XMODIFIERS": "@im=fcitx",
            "GTK_IM_MODULE": "fcitx",
            "QT_IM_MODULE": "fcitx",
            "PATH": "/malicious/path",
            "WINEDLLOVERRIDES": "private",
            "WINEDEBUG": "+all",
            "SECRET_FROM_BROWSER": "must-not-leak",
        }
        with mock.patch.dict(os.environ, inherited, clear=True):
            env, argv = build_wine_command(request, self.paths)

        self.assertEqual(
            argv,
            (
                str(self.wine),
                str(self.paths.client / "Maplestory_Classic.exe"),
                "alpha",
                "beta gamma",
            ),
        )
        self.assertEqual(env["WINEPREFIX"], str(self.paths.prefix))
        self.assertEqual(env["WINEDEBUG"], "-all")
        self.assertEqual(env["LANG"], "zh_TW.UTF-8")
        self.assertEqual(env["PATH"], f"{self.wine_root / 'bin'}:/usr/bin:/bin")
        self.assertEqual(env.get("XMODIFIERS"), "@im=fcitx")
        self.assertEqual(env.get("GTK_IM_MODULE"), "fcitx")
        self.assertEqual(env.get("QT_IM_MODULE"), "fcitx")
        self.assertEqual(env.get("XDG_CONFIG_HOME"), "/home/example/.config")
        self.assertEqual(env.get("XDG_SESSION_TYPE"), "x11")
        self.assertNotIn("WINEDLLOVERRIDES", env)
        self.assertNotIn("SECRET_FROM_BROWSER", env)

    def test_first_launch_after_boot_approves_automatically(self):
        (self.paths.state / "graphics-ok.json").unlink()
        collector = mock.Mock(return_value=self.passing_report())

        result = run_authenticated(
            LaunchRequest("2982", None, ("safe",)),
            self.paths,
            collector=collector,
        )

        self.assertEqual(result, 0)
        collector.assert_called_once_with(self.paths)
        self.assertEqual(
            json.loads((self.paths.state / "graphics-ok.json").read_text()),
            {"schema": 1, "gate_passed": True, "boot_id": self.boot_id},
        )

    def test_existing_current_approval_skips_collector(self):
        collector = mock.Mock(side_effect=AssertionError("must not collect"))

        self.assertEqual(
            run_authenticated(
                LaunchRequest("2982", None, ("safe",)),
                self.paths,
                collector=collector,
            ),
            0,
        )
        collector.assert_not_called()

    def test_no_shell_private_lock_and_devnull_stdio(self):
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch("msclassic.runner.subprocess.run", return_value=completed) as invoked:
            result = run_authenticated(LaunchRequest("2982", None, ("$(touch)",)), self.paths)

        self.assertEqual(result, 0)
        kwargs = invoked.call_args.kwargs
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(stat.S_IMODE((self.paths.state / "launch.lock").stat().st_mode), 0o600)

    def test_launch_status_contains_no_authenticated_arguments(self):
        completed = subprocess.CompletedProcess([], 23)
        with mock.patch("msclassic.runner.subprocess.run", return_value=completed):
            result = run_authenticated(
                LaunchRequest("2982", None, ("private-value",)),
                self.paths,
            )

        status_path = self.paths.state / "last-launch-status.json"
        self.assertEqual(result, 23)
        self.assertEqual(
            json.loads(status_path.read_text()),
            {"schema": 1, "stage": "exited", "exit_code": 23},
        )
        self.assertNotIn("private-value", status_path.read_text())

    def test_authenticated_launch_prepares_input_and_restores_after_wine(self):
        events = []

        def activate(_paths, _environment):
            events.append("activate")
            return InputModeStatus("active", "Temporary game input profile is active")

        def wine(_argv, **_kwargs):
            events.append("wine")
            return subprocess.CompletedProcess([], 0)

        def restore(_paths, _environment):
            events.append("restore")
            return InputModeStatus("inactive", "Game input profile was restored")

        with (
            mock.patch("msclassic.runner.activate_game_input", side_effect=activate),
            mock.patch("msclassic.runner.subprocess.run", side_effect=wine),
            mock.patch("msclassic.runner.restore_game_input", side_effect=restore),
        ):
            result = run_authenticated(
                LaunchRequest("2982", None, ("safe",)),
                self.paths,
            )

        self.assertEqual(result, 0)
        self.assertEqual(events, ["activate", "wine", "restore"])

    def test_authenticated_launch_restores_input_when_wine_spawn_fails(self):
        active = InputModeStatus("active", "Temporary game input profile is active")

        with (
            mock.patch("msclassic.runner.activate_game_input", return_value=active),
            mock.patch("msclassic.runner.subprocess.run", side_effect=OSError("spawn failed")),
            mock.patch("msclassic.runner.restore_game_input") as restored,
        ):
            with self.assertRaises(OSError):
                run_authenticated(
                    LaunchRequest("2982", None, ("safe",)),
                    self.paths,
                )

        restored.assert_called_once()

    def test_duplicate_launch_is_refused_immediately(self):
        lock_path = self.paths.state / "launch.lock"
        lock_path.touch(mode=0o600)
        with lock_path.open("r+") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ActiveSessionError):
                run_authenticated(LaunchRequest("2982", None, ("safe",)), self.paths)

    def test_rejects_runtime_without_matching_stamp_or_writable_client(self):
        with mock.patch("msclassic.runner.patched_runtime_valid", return_value=False):
            with self.assertRaises(RunnerError):
                run_authenticated(LaunchRequest("2982", None, ("safe",)), self.paths)

    def test_launch_refuses_incomplete_ngs_state_before_private_spawn(self):
        (
            self.paths.prefix
            / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
        ).unlink()

        with mock.patch("msclassic.runner.subprocess.run") as invoked:
            with self.assertRaisesRegex(
                RunnerError,
                "NGS service installation is incomplete",
            ):
                run_authenticated(
                    LaunchRequest("2982", None, ("private-value",)),
                    self.paths,
                )

        invoked.assert_not_called()

    def test_handler_install_and_restore_cover_all_observed_schemes(self):
        current = {
            "x-scheme-handler/nexonplug": "previous.desktop",
            "x-scheme-handler/NexonPlug": "",
            "x-scheme-handler/ngm": "old-ngm.desktop",
        }

        def fake_run(argv, **kwargs):
            self.assertFalse(kwargs["shell"])
            if argv[:3] == ["xdg-mime", "query", "default"]:
                return subprocess.CompletedProcess(argv, 0, current[argv[3]] + "\n", "")
            if argv[:2] == ["xdg-mime", "default"]:
                current[argv[3]] = argv[2]
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("msclassic.runner.subprocess.run", side_effect=fake_run):
            installed = install_desktop_handler(self.paths)
            desktop = installed.desktop_file.read_text(encoding="utf-8")
            self.assertIn("x-scheme-handler/nexonplug;", desktop)
            self.assertIn("x-scheme-handler/NexonPlug;", desktop)
            self.assertIn("x-scheme-handler/ngm;", desktop)
            self.assertNotIn("x-scheme-handler/http;", desktop)
            self.assertNotIn("x-scheme-handler/https;", desktop)
            self.assertNotIn("text/html;", desktop)
            self.assertIn(f"Exec={self.home}/.local/bin/msclassic handle-url %u", desktop)
            self.assertEqual(installed.current, "msclassic-ngm.desktop")
            restore_desktop_handler(self.paths)

        self.assertEqual(current["x-scheme-handler/nexonplug"], "previous.desktop")
        self.assertEqual(current["x-scheme-handler/ngm"], "old-ngm.desktop")
        self.assertFalse(installed.desktop_file.exists())


if __name__ == "__main__":
    unittest.main()
