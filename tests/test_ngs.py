import tempfile
import unittest
from pathlib import Path

from msclassic.ngs import inspect_ngs_state
from msclassic.paths import AppPaths


class NgsStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})
        self.paths.prefix.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_services(self, *names):
        registry = "WINE REGISTRY Version 2\n" + "".join(
            f"[System\\\\ControlSet001\\\\Services\\\\{name}] 1\n"
            for name in names
        )
        (self.paths.prefix / "system.reg").write_text(registry, encoding="utf-8")

    def test_partial_service_or_broker_state_is_not_complete(self):
        self.write_services("RpcSs", "PlugPlay")
        baseline_only = inspect_ngs_state(self.paths)

        self.assertTrue(baseline_only.rpcss_registered)
        self.assertTrue(baseline_only.plugplay_registered)
        self.assertFalse(baseline_only.ngs_registered)
        self.assertFalse(baseline_only.broker_installed)
        self.assertFalse(baseline_only.complete)

        broker = (
            self.paths.prefix
            / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
        )
        broker.parent.mkdir(parents=True)
        broker.write_bytes(b"MZ")
        broker_only = inspect_ngs_state(self.paths)

        self.assertTrue(broker_only.broker_installed)
        self.assertFalse(broker_only.ngs_registered)
        self.assertFalse(broker_only.complete)

    def test_complete_state_requires_baseline_service_ngs_and_broker(self):
        self.write_services("RpcSs", "PlugPlay", "NGS")
        broker = (
            self.paths.prefix
            / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
        )
        broker.parent.mkdir(parents=True)
        broker.write_bytes(b"MZ")

        state = inspect_ngs_state(self.paths)

        self.assertTrue(state.rpcss_registered)
        self.assertTrue(state.plugplay_registered)
        self.assertTrue(state.ngs_registered)
        self.assertTrue(state.broker_installed)
        self.assertTrue(state.complete)


if __name__ == "__main__":
    unittest.main()
