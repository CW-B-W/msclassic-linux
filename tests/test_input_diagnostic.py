import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.input_diagnostic import (
    CATEGORY_NAMES,
    DIAGNOSTIC_RECORD,
    InputDiagnosticError,
    arm_input_diagnostic,
    input_diagnostic_status,
    parse_diagnostic_records,
    start_armed_input_diagnostic,
    stop_input_diagnostic,
    summarize_diagnostic,
)
from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths


REPO = Path(__file__).resolve().parents[1]
PATCH = REPO / "patches/wine-11.10-msclassic-input-diagnostic.patch"
BUILDER = REPO / "scripts/build-input-diagnostic-wine.sh"


class InputDiagnosticPatchTests(unittest.TestCase):
    def test_patch_has_all_four_observation_points_and_no_event_routing_change(self):
        text = PATCH.read_text(encoding="utf-8")

        for source in (
            "dlls/winex11.drv/Makefile.in",
            "dlls/winex11.drv/event.c",
            "dlls/winex11.drv/input_diag.c",
            "dlls/winex11.drv/x11drv.h",
            "dlls/winex11.drv/xim.c",
        ):
            self.assertIn(f"+++ b/{source}", text)
        for marker in (
            "MSCLASSIC_DIAG_XIM_FILTERED_KEYBOARD",
            "MSCLASSIC_DIAG_IME_OPEN",
            "MSCLASSIC_DIAG_IME_CLOSED",
            "MSCLASSIC_DIAG_COMPOSITION_RECT_SET",
            "MSCLASSIC_DIAG_COMPOSITION_RECT_CLEAR",
            "MSCLASSIC_DIAG_FOCUS_IN",
            "MSCLASSIC_DIAG_FOCUS_OUT",
        ):
            self.assertIn(f"msclassic_input_diag_record( {marker} )", text)
        self.assertIn("if (XFilterEvent( &event, None ))", text)
        self.assertNotIn("X11DRV_KeyEvent( 0, &event )", text)

    def test_added_diagnostic_code_cannot_record_input_or_authenticated_data(self):
        text = PATCH.read_text(encoding="utf-8")
        added = "\n".join(
            line[1:]
            for line in text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ).lower()

        for forbidden in (
            "keycode",
            "keysym",
            "xlookupstring",
            "xutf8lookupstring",
            "window title",
            "getwindowtext",
            "passarg",
            "nexonplug",
            "bearer",
            "cookie",
            "fprintf",
            "printf(",
        ):
            self.assertNotIn(forbidden, added)
        self.assertIn("write( diagnostic_fd", added)

    def test_builder_locks_source_base_driver_and_side_by_side_output(self):
        text = BUILDER.read_text(encoding="utf-8")

        self.assertIn("4b12965ca7e78b8e45eee5f835c72963b3ce351d", text)
        self.assertIn("5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5", text)
        self.assertIn("wine-tkg-inputdiag-11.10", text)
        self.assertIn("git -C \"$source_dir\" apply --check", text)
        self.assertIn("dlls/winex11.drv/winex11.so", text)
        self.assertIn("cp -a --reflink=auto", text)
        self.assertIn("mv \"$staged_runtime\" \"$output_runtime\"", text)


class InputDiagnosticRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.log = self.directory / "input-123.bin"

    def tearDown(self):
        self.temp.cleanup()

    def write_records(self, records):
        self.log.write_bytes(b"".join(DIAGNOSTIC_RECORD.pack(*record) for record in records))
        self.log.chmod(0o600)

    def test_parser_and_summary_expose_only_categories_and_relative_time(self):
        self.write_records(
            (
                (10_000, 1, 1, 1),
                (12_000, 2, 2, 1),
                (15_000, 3, 4, 1),
            )
        )

        records = parse_diagnostic_records(self.log, self.directory)
        summary = summarize_diagnostic(self.log, self.directory)

        self.assertEqual(records, ((10_000, 1, 1), (12_000, 2, 2), (15_000, 3, 4)))
        self.assertEqual(summary["records"], 3)
        self.assertEqual(summary["duration_ns"], 5_000)
        self.assertEqual(summary["counts"][CATEGORY_NAMES[1]], 1)
        self.assertEqual(summary["counts"][CATEGORY_NAMES[2]], 1)
        self.assertEqual(summary["counts"][CATEGORY_NAMES[4]], 1)
        self.assertNotIn(str(self.log), repr(summary))

    def test_parser_rejects_symlink_mode_size_schema_and_unknown_category(self):
        self.write_records(((10_000, 1, 1, 1),))
        self.log.chmod(0o644)
        with self.assertRaises(InputDiagnosticError):
            parse_diagnostic_records(self.log, self.directory)

        self.log.chmod(0o600)
        link = self.directory / "link.bin"
        link.symlink_to(self.log)
        with self.assertRaises(InputDiagnosticError):
            parse_diagnostic_records(link, self.directory)

        self.log.write_bytes(b"short")
        self.log.chmod(0o600)
        with self.assertRaises(InputDiagnosticError):
            parse_diagnostic_records(self.log, self.directory)

        self.write_records(((10_000, 1, 99, 1),))
        with self.assertRaises(InputDiagnosticError):
            parse_diagnostic_records(self.log, self.directory)

        self.write_records(((10_000, 1, 1, 2),))
        with self.assertRaises(InputDiagnosticError):
            parse_diagnostic_records(self.log, self.directory)


class InputDiagnosticLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment(
            {"HOME": str(self.home), "XDG_STATE_HOME": str(self.root / "state")}
        )
        self.artifact = Artifact(
            "wine",
            "wine-test",
            "https://example.invalid/wine.tar.xz",
            "sha256",
            "a" * 64,
            1,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_arm_start_and_close_use_private_one_shot_state(self):
        runtime = self.paths.tools / "wine-test-msclassic-inputdiag1"
        with (
            mock.patch("msclassic.input_diagnostic.diagnostic_runtime_valid", return_value=True),
            mock.patch("msclassic.input_diagnostic.diagnostic_runtime_root", return_value=runtime),
        ):
            armed = arm_input_diagnostic(self.paths, self.artifact)
            marker = self.paths.state / "input-diagnostic/armed.json"
            self.assertEqual(armed.state, "armed")
            self.assertEqual(input_diagnostic_status(self.paths).state, "armed")
            self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)

            session = start_armed_input_diagnostic(self.paths, self.artifact)
            self.assertIsNotNone(session)
            self.assertEqual(session.wine_root, runtime)
            self.assertEqual(input_diagnostic_status(self.paths).state, "capturing")
            self.assertFalse(marker.exists())
            self.assertEqual(stat.S_IMODE(session.log_path.stat().st_mode), 0o600)

            session.close()
            self.assertEqual(input_diagnostic_status(self.paths).state, "inactive")

    def test_missing_runtime_refuses_arm_and_stop_is_idempotent(self):
        with mock.patch("msclassic.input_diagnostic.diagnostic_runtime_valid", return_value=False):
            with self.assertRaises(InputDiagnosticError):
                arm_input_diagnostic(self.paths, self.artifact)
        self.assertEqual(stop_input_diagnostic(self.paths).state, "inactive")
        self.assertEqual(stop_input_diagnostic(self.paths).state, "inactive")


if __name__ == "__main__":
    unittest.main()
