import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from msclassic.audit import (
    DriftError,
    TrialError,
    TrialRecorder,
    TrialSpec,
    compare_reference,
)
from msclassic.commands import CommandError, run_allowlisted
from msclassic.redaction import UnsafeExportError


class AllowlistedCommandTests(unittest.TestCase):
    def test_runs_real_allowlisted_binary_and_sanitizes_output(self):
        with tempfile.TemporaryDirectory() as td:
            probe = Path(td) / "probe"
            probe.write_text("#!/bin/sh\nprintf 'OTP=1234567890\\n'\n", encoding="utf-8")
            probe.chmod(0o700)
            result = run_allowlisted("probe", [str(probe)], {probe.resolve()})

        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("1234567890", result.stdout)
        self.assertEqual(result.category, "probe")

    def test_rejects_unlisted_binary_and_sensitive_argv(self):
        with self.assertRaises(CommandError):
            run_allowlisted("probe", ["/bin/echo", "safe"], {Path(sys.executable)})
        with self.assertRaises(CommandError):
            run_allowlisted(
                "probe",
                [sys.executable, "nexonplug://?passarg=secret"],
                {Path(sys.executable).resolve()},
            )


class TrialAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runs = Path(self.temp.name) / "runs"
        self.clock = lambda: datetime(2026, 8, 26, 8, 0, 0, tzinfo=timezone.utc)
        self.spec = TrialSpec(
            name="venus-2g",
            hypothesis="VirGL provides accelerated OpenGL",
            variable="opengl_renderer",
            before="llvmpipe",
            after="virgl",
            expected="VirGL renderer appears",
            pass_rule="gate_passed=true",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_trial_requires_exactly_one_named_variable(self):
        with self.assertRaises(TrialError):
            TrialSpec("bad", "x", "hostmem,proton", "a", "b", "x", "x")
        with self.assertRaises(TrialError):
            TrialSpec("bad", "x", "", "a", "b", "x", "x")

    def test_finish_writes_deterministic_private_manifest_and_report(self):
        recorder = TrialRecorder(self.runs, self.clock).begin(
            self.spec,
            {"kernel": "6.17.0", "renderer": "llvmpipe", "gate_passed": False},
        )
        recorder.record(
            run_allowlisted(
                "probe",
                [sys.executable, "-c", "print('renderer checked')"],
                {Path(sys.executable).resolve()},
            )
        )
        recorder.observe("AnyDesk reconnected; no launch credentials used")

        run_dir = recorder.finish("candidate")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["trial"]["variable"], "opengl_renderer")
        self.assertEqual(manifest["disposition"], "candidate")
        self.assertEqual(manifest["commands"][0]["category"], "probe")
        self.assertNotIn("argv", manifest["commands"][0])
        self.assertEqual(os.stat(run_dir).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(run_dir / "manifest.json").st_mode & 0o777, 0o600)
        first_bytes = (run_dir / "manifest.json").read_bytes()
        second = TrialRecorder(Path(self.temp.name) / "other", self.clock).begin(
            self.spec,
            {"kernel": "6.17.0", "renderer": "llvmpipe", "gate_passed": False},
        )
        second.record(recorder.command_results[0])
        second.observe("AnyDesk reconnected; no launch credentials used")
        second_dir = second.finish("candidate")
        self.assertEqual(first_bytes, (second_dir / "manifest.json").read_bytes())

    def test_observation_rejects_sensitive_content(self):
        recorder = TrialRecorder(self.runs, self.clock).begin(self.spec, {"gate_passed": False})
        with self.assertRaises(UnsafeExportError):
            recorder.observe("nexonplug://?game=2982&passarg=secret")

    def test_drift_refuses_by_default_and_accepts_as_candidate_only(self):
        reference = {"profile": "venus", "proton": "wine-11.10"}
        candidate = {"profile": "venus", "proton": "wine-11.11"}
        with self.assertRaises(DriftError):
            compare_reference(reference, candidate, accept_drift=False)

        self.assertEqual(compare_reference(reference, candidate, accept_drift=True), ["proton"])


if __name__ == "__main__":
    unittest.main()

