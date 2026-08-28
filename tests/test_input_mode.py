import unittest

from msclassic.input_mode import _transform_lxqt, _transform_openbox


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


if __name__ == "__main__":
    unittest.main()
