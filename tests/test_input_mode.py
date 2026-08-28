import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from msclassic.input_mode import (
    InputModeStatus,
    _transform_lxqt,
    _transform_openbox,
    activate_game_input,
    deactivate_fcitx,
    game_input_status,
    restore_game_input,
)
from msclassic.paths import AppPaths


OPENBOX_SAMPLE = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<openbox_config>
  <keyboard>
    <keybind key=\"A-space\"><action name=\"ShowMenu\" /></keybind>
    <keybind key=\"A-Tab\"><action name=\"NextWindow\" /></keybind>
    <keybind key=\"A-S-Tab\"><action name=\"PreviousWindow\" /></keybind>
    <keybind key=\"A-F4\"><action name=\"Close\" /></keybind>
    <keybind key=\"W-d\"><action name=\"ToggleShowDesktop\" /></keybind>
  </keyboard>
</openbox_config>
"""

LXQT_SAMPLE = b"""[General]
MultipleActionsBehaviour=first

[Alt%2BSpace.1]
Enabled=true
Exec=window-menu

[Meta%2BD.2]
Enabled=true
Exec=show-desktop

[Print.3]
Enabled=true
Exec=screenshot

[XF86AudioMute.4]
Enabled=true
Exec=volume-mute
"""


class InputModeTransformTests(unittest.TestCase):
    def test_openbox_profile_keeps_only_alt_tab_bindings(self):
        transformed = _transform_openbox(OPENBOX_SAMPLE)

        self.assertIn(b'key="A-Tab"', transformed)
        self.assertIn(b'key="A-S-Tab"', transformed)
        self.assertNotIn(b'key="A-space"', transformed)
        self.assertNotIn(b'key="A-F4"', transformed)
        self.assertNotIn(b'key="W-d"', transformed)

    def test_lxqt_profile_disables_desktop_keys_and_keeps_hardware_keys(self):
        transformed = _transform_lxqt(LXQT_SAMPLE).decode("utf-8")

        self.assertIn("[Alt%2BSpace.1]\nEnabled=false", transformed)
        self.assertIn("[Meta%2BD.2]\nEnabled=false", transformed)
        self.assertIn("[Print.3]\nEnabled=false", transformed)
        self.assertIn("[XF86AudioMute.4]\nEnabled=true", transformed)


class InputModeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.config = self.home / ".config"
        self.home.mkdir()
        self.paths = AppPaths.from_environment(
            {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.config)}
        )
        self.openbox = self.config / "openbox/rc.xml"
        self.lxqt = self.config / "lxqt/globalkeyshortcuts.conf"
        self.system_openbox = self.root / "system-openbox.xml"
        self.system_lxqt = self.root / "system-lxqt.conf"
        self.openbox.parent.mkdir(parents=True)
        self.lxqt.parent.mkdir(parents=True)
        self.openbox.write_bytes(OPENBOX_SAMPLE)
        self.lxqt.write_bytes(LXQT_SAMPLE)
        self.system_openbox.write_bytes(OPENBOX_SAMPLE)
        self.system_lxqt.write_bytes(LXQT_SAMPLE)
        self.environment = {
            "DISPLAY": ":0",
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_SESSION_TYPE": "x11",
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_deactivate_fcitx_uses_fixed_argv_and_is_nonfatal(self):
        environment = {
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        }
        with (
            mock.patch(
                "msclassic.input_mode.shutil.which",
                return_value="/usr/bin/fcitx5-remote",
            ),
            mock.patch(
                "msclassic.input_mode.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as invoked,
        ):
            result = deactivate_fcitx(environment)

        self.assertEqual(result, InputModeStatus("prepared", "Fcitx was deactivated"))
        invoked.assert_called_once_with(
            ["/usr/bin/fcitx5-remote", "-c"],
            shell=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    def test_activate_then_restore_returns_exact_prior_files(self):
        before_openbox = self.openbox.read_bytes()
        before_lxqt = self.lxqt.read_bytes()
        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode.SYSTEM_LXQT", self.system_lxqt),
            mock.patch(
                "msclassic.input_mode.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
        ):
            active = activate_game_input(self.paths, self.environment)
            restored = restore_game_input(self.paths, self.environment)

        self.assertEqual(active.state, "active")
        self.assertEqual(restored.state, "inactive")
        self.assertEqual(self.openbox.read_bytes(), before_openbox)
        self.assertEqual(self.lxqt.read_bytes(), before_lxqt)
        self.assertFalse((self.paths.state / "input-profile/active.json").exists())

    def test_status_reports_inactive_without_a_transaction(self):
        status = game_input_status(self.paths, self.environment)

        self.assertEqual(status, InputModeStatus("inactive", "No game input profile is active"))

    def test_status_reports_malformed_private_transaction(self):
        transaction = self.paths.state / "input-profile/active.json"
        transaction.parent.mkdir(parents=True)
        transaction.write_text("not json", encoding="utf-8")

        status = game_input_status(self.paths, self.environment)

        self.assertEqual(status.state, "malformed")

    def test_unsupported_session_leaves_configuration_unchanged(self):
        before = self.openbox.read_bytes(), self.lxqt.read_bytes()

        status = activate_game_input(
            self.paths,
            {**self.environment, "XDG_SESSION_TYPE": "wayland"},
        )

        self.assertEqual(status.state, "unavailable")
        self.assertEqual((self.openbox.read_bytes(), self.lxqt.read_bytes()), before)

    def test_activation_reload_failure_restores_both_files(self):
        before = self.openbox.read_bytes(), self.lxqt.read_bytes()

        def command_result(argv, **_kwargs):
            return subprocess.CompletedProcess(
                argv,
                1 if argv == ["openbox", "--reconfigure"] else 0,
            )

        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode.SYSTEM_LXQT", self.system_lxqt),
            mock.patch("msclassic.input_mode.subprocess.run", side_effect=command_result),
        ):
            status = activate_game_input(self.paths, self.environment)

        self.assertEqual(status.state, "unavailable")
        self.assertEqual((self.openbox.read_bytes(), self.lxqt.read_bytes()), before)
        self.assertFalse((self.paths.state / "input-profile/active.json").exists())

    def test_restore_is_idempotent(self):
        self.assertEqual(
            restore_game_input(self.paths, self.environment).state,
            "inactive",
        )
        self.assertEqual(
            restore_game_input(self.paths, self.environment).state,
            "inactive",
        )

    def test_stale_transaction_is_restored_before_a_new_activation(self):
        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode.SYSTEM_LXQT", self.system_lxqt),
            mock.patch(
                "msclassic.input_mode.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
        ):
            self.assertEqual(
                activate_game_input(self.paths, self.environment).state,
                "active",
            )
            self.assertEqual(
                activate_game_input(self.paths, self.environment).state,
                "active",
            )
            self.assertEqual(
                restore_game_input(self.paths, self.environment).state,
                "inactive",
            )

    def test_restore_removes_generated_files_when_no_prior_user_files_existed(self):
        self.openbox.unlink()
        self.lxqt.unlink()
        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode.SYSTEM_LXQT", self.system_lxqt),
            mock.patch(
                "msclassic.input_mode.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
        ):
            activate_game_input(self.paths, self.environment)
            restore_game_input(self.paths, self.environment)

        self.assertFalse(self.openbox.exists())
        self.assertFalse(self.lxqt.exists())

    def test_fcitx_missing_or_nonzero_result_does_not_raise(self):
        with mock.patch("msclassic.input_mode.shutil.which", return_value=None):
            self.assertEqual(
                deactivate_fcitx(self.environment).state,
                "unavailable",
            )
        with (
            mock.patch(
                "msclassic.input_mode.shutil.which",
                return_value="/usr/bin/fcitx5-remote",
            ),
            mock.patch(
                "msclassic.input_mode.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ),
        ):
            self.assertEqual(
                deactivate_fcitx(
                    {**self.environment, "DBUS_SESSION_BUS_ADDRESS": "bus"}
                ).state,
                "unavailable",
            )


if __name__ == "__main__":
    unittest.main()
