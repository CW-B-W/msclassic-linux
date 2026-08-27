import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.approval import GraphicsApprovalError, ensure_current_boot_approval
from msclassic.doctor import GraphicsReport
from msclassic.paths import AppPaths


def report(*, boot_id="boot-new", passes=True):
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
        boot_id=boot_id,
    )


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})

    def tearDown(self):
        self.temp.cleanup()

    def stamp(self, boot_id):
        self.paths.state.mkdir(parents=True, exist_ok=True)
        path = self.paths.state / "graphics-ok.json"
        path.write_text(
            json.dumps({"schema": 1, "gate_passed": True, "boot_id": boot_id}),
            encoding="utf-8",
        )
        return path

    def test_current_stamp_skips_collection(self):
        self.stamp("boot-new")
        collector = mock.Mock(side_effect=AssertionError("must not collect"))

        result = ensure_current_boot_approval(
            self.paths,
            collector,
            boot_id_reader=lambda: "boot-new",
        )

        self.assertTrue(result.reused)
        collector.assert_not_called()

    def test_missing_or_stale_stamp_collects_once_and_writes_private_stamp(self):
        for initial in (None, "boot-old"):
            with self.subTest(initial=initial):
                (self.paths.state / "graphics-ok.json").unlink(missing_ok=True)
                if initial:
                    self.stamp(initial)
                collector = mock.Mock(return_value=report())

                result = ensure_current_boot_approval(
                    self.paths,
                    collector,
                    boot_id_reader=lambda: "boot-new",
                )

                self.assertFalse(result.reused)
                collector.assert_called_once_with(self.paths)
                stamp_path = self.paths.state / "graphics-ok.json"
                self.assertEqual(
                    json.loads(stamp_path.read_text(encoding="utf-8")),
                    {"schema": 1, "gate_passed": True, "boot_id": "boot-new"},
                )
                self.assertEqual(stat.S_IMODE(stamp_path.stat().st_mode), 0o600)

    def test_failure_leaves_no_stamp_and_never_exposes_collector_details(self):
        stamp_path = self.stamp("boot-old")
        cases = (
            mock.Mock(return_value=report(passes=False)),
            mock.Mock(side_effect=RuntimeError("private-authentication-value")),
        )
        for collector in cases:
            with self.subTest(collector=collector):
                self.stamp("boot-old")
                with self.assertRaisesRegex(
                    GraphicsApprovalError,
                    "graphics launch check failed",
                ) as raised:
                    ensure_current_boot_approval(
                        self.paths,
                        collector,
                        boot_id_reader=lambda: "boot-new",
                    )
                self.assertNotIn("private-authentication-value", str(raised.exception))
                self.assertFalse(stamp_path.exists())


if __name__ == "__main__":
    unittest.main()
