import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import msclassic.debugger as debugger
from msclassic.lockfile import load_versions
from msclassic.paths import AppPaths
from msclassic.runtime import patched_runtime_root


REPO = Path(__file__).resolve().parents[1]


class DebuggerLauncherTests(unittest.TestCase):
    def test_build_uses_the_game_prefix_and_pinned_wine(self):
        builder = getattr(debugger, "build_windows_ce_command", None)
        self.assertIsNotNone(builder)
        if builder is None:
            return

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            paths = AppPaths.from_environment({"HOME": str(home)})
            artifact = load_versions(REPO / "versions.lock")["wine"]
            wine = patched_runtime_root(paths, artifact) / "bin/wine"
            ce = home / "tools/Cheat Engine/cheatengine-x86_64.exe"
            inherited = {
                "DISPLAY": ":0",
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "PATH": "/untrusted/bin",
                "WINEPREFIX": "/wrong-prefix",
                "SECRET_FROM_BROWSER": "must-not-leak",
            }

            with mock.patch.dict(os.environ, inherited, clear=True):
                environment, argv = builder(ce, paths)

        self.assertEqual(argv, (str(wine), str(ce)))
        self.assertEqual(environment["WINEPREFIX"], str(paths.prefix))
        self.assertEqual(environment["WINEDEBUG"], "-all")
        self.assertEqual(
            environment["PATH"], f"{wine.parent}:/usr/bin:/bin"
        )
        self.assertNotIn("SECRET_FROM_BROWSER", environment)

    def test_run_rejects_a_non_windows_debugger_before_spawning(self):
        runner = getattr(debugger, "run_windows_ce", None)
        error = getattr(debugger, "DebuggerError", None)
        self.assertIsNotNone(runner)
        self.assertIsNotNone(error)
        if runner is None or error is None:
            return

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            paths = AppPaths.from_environment({"HOME": str(home)})
            native_ce = home / "cheatengine-x86_64"
            native_ce.write_bytes(b"ELF")

            with mock.patch("msclassic.debugger.subprocess.run") as spawned:
                with self.assertRaisesRegex(error, "Windows Cheat Engine executable"):
                    runner(native_ce, paths)

        spawned.assert_not_called()

    def test_run_starts_windows_ce_inside_the_game_wine_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            paths = AppPaths.from_environment({"HOME": str(home)})
            artifact = load_versions(REPO / "versions.lock")["wine"]
            wine = patched_runtime_root(paths, artifact) / "bin/wine"
            wine.parent.mkdir(parents=True)
            wine.write_bytes(b"wine")
            wine.chmod(0o700)
            paths.prefix.mkdir(parents=True)
            ce = home / "tools/Cheat Engine/cheatengine-x86_64.exe"
            ce.parent.mkdir(parents=True)
            ce.write_bytes(b"MZ")

            completed = subprocess.CompletedProcess([], 7)
            with mock.patch(
                "msclassic.debugger.patched_runtime_valid", return_value=True, create=True
            ):
                with mock.patch(
                    "msclassic.debugger.subprocess.run", return_value=completed
                ) as spawned:
                    result = debugger.run_windows_ce(ce, paths)

        self.assertEqual(result, 7)
        argv = spawned.call_args.args[0]
        kwargs = spawned.call_args.kwargs
        self.assertEqual(argv, [str(wine), str(ce.resolve())])
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(paths.prefix))
        self.assertFalse(kwargs["shell"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
