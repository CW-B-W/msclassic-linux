import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.input_mode import (
    InputModeError,
    InputModeStatus,
    LxqtAction,
    _is_hardware_action,
    _parse_lxqt_actions,
    _session_supported,
    _transform_openbox,
    activate_game_input,
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

BUSCTL_SAMPLE = (
    'a{t(ssbss)} 4 '
    '1 "Alt+Meta+S" "Orca" true "command" "/usr/bin/orca --replace" '
    '2 "XF86AudioMute" "Mute/unmute sound volume" true "client" "/panel/volume/mute" '
    '3 "Shift+Control+F6" "brightness down" true "command" "lxqt-config-brightness -d" '
    '4 "Control+Alt+T" "Launch Terminal" false "command" "qterminal"\n'
)


class InputModeTransformTests(unittest.TestCase):
    def test_openbox_profile_keeps_only_alt_tab_bindings(self):
        transformed = _transform_openbox(OPENBOX_SAMPLE)

        self.assertIn(b'key="A-Tab"', transformed)
        self.assertIn(b'key="A-S-Tab"', transformed)
        self.assertNotIn(b'key="A-space"', transformed)
        self.assertNotIn(b'key="A-F4"', transformed)
        self.assertNotIn(b'key="W-d"', transformed)

    def test_lxqt_reply_parses_fixed_action_signature(self):
        self.assertEqual(
            _parse_lxqt_actions(BUSCTL_SAMPLE),
            (
                LxqtAction(1, "Alt+Meta+S", "Orca", True, "command", "/usr/bin/orca --replace"),
                LxqtAction(2, "XF86AudioMute", "Mute/unmute sound volume", True, "client", "/panel/volume/mute"),
                LxqtAction(3, "Shift+Control+F6", "brightness down", True, "command", "lxqt-config-brightness -d"),
                LxqtAction(4, "Control+Alt+T", "Launch Terminal", False, "command", "qterminal"),
            ),
        )

    def test_lxqt_reply_rejects_wrong_count_or_boolean(self):
        with self.assertRaises(InputModeError):
            _parse_lxqt_actions(BUSCTL_SAMPLE.replace("a{t(ssbss)} 4", "a{t(ssbss)} 5"))
        with self.assertRaises(InputModeError):
            _parse_lxqt_actions(BUSCTL_SAMPLE.replace(" true ", " maybe ", 1))

    def test_hardware_actions_include_xf86_and_brightness_bindings(self):
        actions = _parse_lxqt_actions(BUSCTL_SAMPLE)

        self.assertFalse(_is_hardware_action(actions[0]))
        self.assertTrue(_is_hardware_action(actions[1]))
        self.assertTrue(_is_hardware_action(actions[2]))
        self.assertFalse(_is_hardware_action(actions[3]))


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
        self.openbox.parent.mkdir(parents=True)
        self.lxqt.parent.mkdir(parents=True)
        self.openbox.write_bytes(OPENBOX_SAMPLE)
        self.lxqt.write_bytes(b"must remain byte-for-byte unchanged\n")
        self.system_openbox.write_bytes(OPENBOX_SAMPLE)
        self.environment = {
            "DISPLAY": ":0",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_SESSION_TYPE": "x11",
        }
        self.actions = _parse_lxqt_actions(BUSCTL_SAMPLE)

    def tearDown(self):
        self.temp.cleanup()

    def lifecycle(self):
        changed = []

        def set_enabled(action_id, enabled, _environment):
            changed.append((action_id, enabled))

        return changed, (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode._session_supported", return_value=True),
            mock.patch("msclassic.input_mode._list_lxqt_actions", return_value=self.actions),
            mock.patch("msclassic.input_mode._set_lxqt_action_enabled", side_effect=set_enabled),
            mock.patch("msclassic.input_mode._reload_openbox"),
        )

    def test_activate_then_restore_replays_exact_dbus_states_and_openbox(self):
        before_openbox = self.openbox.read_bytes()
        before_lxqt = self.lxqt.read_bytes()
        changed, patches = self.lifecycle()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            active = activate_game_input(self.paths, self.environment)
            transaction = json.loads(
                (self.paths.state / "input-profile/active.json").read_text()
            )
            restored = restore_game_input(self.paths, self.environment)

        self.assertEqual(active.state, "active")
        self.assertEqual(restored.state, "inactive")
        self.assertEqual(changed[:1], [(1, False)])
        self.assertEqual(changed[1:], [(1, True), (2, True), (3, True), (4, False)])
        self.assertEqual(transaction["schema"], 2)
        self.assertEqual(
            transaction["lxqt_actions"],
            [
                {"enabled": True, "id": 1},
                {"enabled": True, "id": 2},
                {"enabled": True, "id": 3},
                {"enabled": False, "id": 4},
            ],
        )
        self.assertEqual(self.openbox.read_bytes(), before_openbox)
        self.assertEqual(self.lxqt.read_bytes(), before_lxqt)
        self.assertFalse((self.paths.state / "input-profile/active.json").exists())

    def test_partial_lxqt_failure_rolls_back_and_keeps_openbox_profile(self):
        expanded = self.actions + (
            LxqtAction(5, "Meta+D", "Show desktop", True, "client", "/panel/showdesktop/show_hide"),
        )
        changed = []

        def set_enabled(action_id, enabled, _environment):
            changed.append((action_id, enabled))
            if (action_id, enabled) == (5, False):
                raise InputModeError("simulated D-Bus failure")

        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode._session_supported", return_value=True),
            mock.patch("msclassic.input_mode._list_lxqt_actions", return_value=expanded),
            mock.patch("msclassic.input_mode._set_lxqt_action_enabled", side_effect=set_enabled),
            mock.patch("msclassic.input_mode._reload_openbox"),
        ):
            status = activate_game_input(self.paths, self.environment)
            transaction = json.loads(
                (self.paths.state / "input-profile/active.json").read_text()
            )

        self.assertEqual(status.state, "active")
        self.assertEqual(
            changed,
            [(1, False), (5, False), (5, True), (1, True)],
        )
        self.assertEqual(transaction["lxqt_actions"], [])
        self.assertNotIn(b'key="A-space"', self.openbox.read_bytes())
        self.assertEqual(self.lxqt.read_bytes(), b"must remain byte-for-byte unchanged\n")

    def test_unavailable_lxqt_keeps_independent_openbox_profile(self):
        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode._session_supported", return_value=True),
            mock.patch("msclassic.input_mode._list_lxqt_actions", side_effect=InputModeError("missing")),
            mock.patch("msclassic.input_mode._reload_openbox"),
        ):
            status = activate_game_input(self.paths, self.environment)

        self.assertEqual(status.state, "active")
        self.assertIn("LXQt shortcuts unavailable", status.detail)
        self.assertNotIn(b'key="A-space"', self.openbox.read_bytes())

    def test_status_reports_inactive_without_a_transaction(self):
        self.assertEqual(
            game_input_status(self.paths, self.environment),
            InputModeStatus("inactive", "No game input profile is active"),
        )

    def test_status_reports_malformed_private_transaction(self):
        transaction = self.paths.state / "input-profile/active.json"
        transaction.parent.mkdir(parents=True)
        transaction.write_text("not json", encoding="utf-8")

        self.assertEqual(game_input_status(self.paths, self.environment).state, "malformed")

    def test_unsupported_session_leaves_configuration_unchanged(self):
        before = self.openbox.read_bytes(), self.lxqt.read_bytes()

        status = activate_game_input(
            self.paths,
            {**self.environment, "XDG_SESSION_TYPE": "wayland"},
        )

        self.assertEqual(status.state, "unavailable")
        self.assertEqual((self.openbox.read_bytes(), self.lxqt.read_bytes()), before)

    def test_openbox_reload_failure_restores_file_and_lxqt_states(self):
        changed = []

        def set_enabled(action_id, enabled, _environment):
            changed.append((action_id, enabled))

        with (
            mock.patch("msclassic.input_mode.SYSTEM_OPENBOX", self.system_openbox),
            mock.patch("msclassic.input_mode._session_supported", return_value=True),
            mock.patch("msclassic.input_mode._list_lxqt_actions", return_value=self.actions),
            mock.patch("msclassic.input_mode._set_lxqt_action_enabled", side_effect=set_enabled),
            mock.patch("msclassic.input_mode._reload_openbox", side_effect=InputModeError("failed")),
        ):
            status = activate_game_input(self.paths, self.environment)

        self.assertEqual(status.state, "unavailable")
        self.assertEqual(self.openbox.read_bytes(), OPENBOX_SAMPLE)
        self.assertEqual(changed, [(1, True), (2, True), (3, True), (4, False)])
        self.assertFalse((self.paths.state / "input-profile/active.json").exists())

    def test_restore_is_idempotent(self):
        self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")
        self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")

    def test_stale_transaction_is_restored_before_new_activation(self):
        changed, patches = self.lifecycle()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            self.assertEqual(activate_game_input(self.paths, self.environment).state, "active")
            self.assertEqual(activate_game_input(self.paths, self.environment).state, "active")
            self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")

        self.assertGreaterEqual(changed.count((1, True)), 2)

    def test_restore_removes_generated_openbox_when_none_existed(self):
        self.openbox.unlink()
        changed, patches = self.lifecycle()
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            activate_game_input(self.paths, self.environment)
            restore_game_input(self.paths, self.environment)

        self.assertFalse(self.openbox.exists())
        self.assertEqual(self.lxqt.read_bytes(), b"must remain byte-for-byte unchanged\n")

    def test_session_check_requires_x11_display_and_openbox_only(self):
        with mock.patch("msclassic.input_mode.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as invoked:
            self.assertTrue(_session_supported(self.environment))

        invoked.assert_called_once_with(
            ["pgrep", "-x", "openbox"],
            shell=False,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
