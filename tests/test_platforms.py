import unittest
from pathlib import Path

from msclassic.platforms import UnsupportedPlatformError, select_platform


REPO = Path(__file__).resolve().parents[1]


class PlatformSelectionTests(unittest.TestCase):
    def test_ubuntu_2404_selects_lubuntu_adapter(self):
        adapter = select_platform(
            None,
            {"ID": "ubuntu", "VERSION_ID": "24.04", "ID_LIKE": "debian"},
        )

        self.assertEqual(adapter.id, "lubuntu-24.04")
        self.assertIn("mesa-utils", adapter.package_names)
        self.assertIn("mesa-vulkan-drivers:i386", adapter.package_names)
        for package in (
            "g++",
            "libx11-dev",
            "libxext-dev",
            "libxrender-dev",
            "libxrandr-dev",
            "libxi-dev",
            "libxkbfile-dev",
            "libxinerama-dev",
            "libxcursor-dev",
            "libxcomposite-dev",
            "libxfixes-dev",
            "libxxf86vm-dev",
            "libxshmfence-dev",
            "libxpresent-dev",
            "libxdamage-dev",
            "libxkbregistry-dev",
        ):
            self.assertIn(package, adapter.package_names)
        self.assertEqual(
            adapter.chromium_policy_dir,
            "/etc/chromium/policies/managed",
        )

    def test_explicit_matching_adapter_is_accepted(self):
        adapter = select_platform(
            "lubuntu-24.04",
            {"ID": "ubuntu", "VERSION_ID": "24.04"},
        )

        self.assertEqual(adapter.id, "lubuntu-24.04")

    def test_unsupported_platforms_have_fixed_error(self):
        cases = (
            (None, {"ID": "fedora", "VERSION_ID": "42"}),
            (None, {"ID": "arch"}),
            (None, {"ID": "ubuntu", "VERSION_ID": "24.10"}),
            ("fedora-42", {"ID": "ubuntu", "VERSION_ID": "24.04"}),
            ("lubuntu-24.04", {"ID": "fedora", "VERSION_ID": "42"}),
        )
        for requested, release in cases:
            with self.subTest(requested=requested, release=release):
                with self.assertRaisesRegex(
                    UnsupportedPlatformError,
                    "unsupported platform; currently supported: lubuntu-24.04",
                ):
                    select_platform(requested, release)

    def test_docs_describe_game_input_mode_and_restore(self):
        text = (REPO / "docs/quick-start-lubuntu-pve.md").read_text(encoding="utf-8")

        self.assertIn("msclassic input status", text)
        self.assertIn("msclassic input restore", text)
        self.assertIn("Alt+Tab", text)


if __name__ == "__main__":
    unittest.main()
