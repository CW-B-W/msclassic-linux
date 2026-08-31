import hashlib
import tempfile
import unittest
from pathlib import Path

from msclassic.lockfile import LockfileError, load_versions, verify_file
from msclassic.paths import AppPaths


class PathsAndLockTests(unittest.TestCase):
    def test_xdg_paths_are_derived_without_touching_home(self):
        paths = AppPaths.from_environment(
            {
                "HOME": "/tmp/alice",
                "XDG_CONFIG_HOME": "/cfg",
                "XDG_DATA_HOME": "/data",
                "XDG_STATE_HOME": "/state",
                "XDG_CACHE_HOME": "/cache",
            }
        )

        self.assertEqual(paths.client, Path("/tmp/alice/Games/MapleStoryClassic"))
        self.assertEqual(paths.prefix, Path("/data/maplestory-classic/prefix-wine1110"))
        self.assertEqual(paths.runs, Path("/state/maplestory-classic/runs"))
        self.assertEqual(paths.cache, Path("/cache/maplestory-classic"))

    def test_defaults_follow_xdg_base_directory_rules(self):
        paths = AppPaths.from_environment({"HOME": "/home/alice"})

        self.assertEqual(paths.config, Path("/home/alice/.config/maplestory-classic"))
        self.assertEqual(paths.data, Path("/home/alice/.local/share/maplestory-classic"))
        self.assertEqual(paths.state, Path("/home/alice/.local/state/maplestory-classic"))
        self.assertEqual(paths.cache, Path("/home/alice/.cache/maplestory-classic"))

    def test_loads_valid_artifact_and_verifies_file(self):
        payload = b"locked payload"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root / "versions.lock"
            lock.write_text(
                "\n".join(
                    [
                        "schema = 1",
                        "[sample]",
                        'version = "1.0"',
                        'url = "https://example.invalid/sample.bin"',
                        'algorithm = "sha256"',
                        f'digest = "{digest}"',
                        f"size = {len(payload)}",
                    ]
                ),
                encoding="utf-8",
            )
            artifact_file = root / "sample.bin"
            artifact_file.write_bytes(payload)

            artifacts = load_versions(lock)

            self.assertEqual(artifacts["sample"].version, "1.0")
            self.assertTrue(verify_file(artifact_file, artifacts["sample"]))
            artifact_file.write_bytes(payload + b"!")
            self.assertFalse(verify_file(artifact_file, artifacts["sample"]))

    def test_lock_rejects_bad_digest_length(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "bad.lock"
            lock.write_text(
                "\n".join(
                    [
                        "schema = 1",
                        "[sample]",
                        'version = "1.0"',
                        'url = "https://example.invalid/sample.bin"',
                        'algorithm = "sha256"',
                        'digest = "abc"',
                        "size = 3",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(LockfileError):
                load_versions(lock)

    def test_lock_rejects_non_https_and_unknown_keys(self):
        with tempfile.TemporaryDirectory() as td:
            lock = Path(td) / "bad.lock"
            lock.write_text(
                "\n".join(
                    [
                        "schema = 1",
                        "[sample]",
                        'version = "1.0"',
                        'url = "http://example.invalid/sample.bin"',
                        'algorithm = "sha256"',
                        'digest = "' + ("0" * 64) + '"',
                        "size = 3",
                        'surprise = "no"',
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(LockfileError):
                load_versions(lock)


if __name__ == "__main__":
    unittest.main()
