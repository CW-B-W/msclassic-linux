import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths
from msclassic.runtime import (
    PATCHED_BUILD_CACHE,
    NTDLL_RELATIVE,
    PATCHED_NTDLL_SIZE,
    PATCH_STAMP,
    patched_runtime_manifest,
    patched_runtime_build_supported,
    patched_runtime_root,
    patched_runtime_valid,
)


class PatchedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        home = Path(self.temporary.name) / "home"
        home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(home)})
        self.artifact = Artifact(
            name="wine",
            version="wine-test",
            url="https://example.invalid/wine.tar.xz",
            algorithm="sha256",
            digest="a" * 64,
            size=1,
        )
        self.root = patched_runtime_root(self.paths, self.artifact)
        (self.root / "bin").mkdir(parents=True)
        for name in ("wine", "wineserver"):
            executable = self.root / "bin" / name
            executable.write_bytes(b"tool")
            executable.chmod(0o700)
        (self.root / ".msclassic-artifact.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": self.artifact.name,
                    "version": self.artifact.version,
                    "digest": self.artifact.digest,
                }
            ),
            encoding="utf-8",
        )
        (self.root / PATCH_STAMP).write_text(
            json.dumps(patched_runtime_manifest(self.artifact)), encoding="utf-8"
        )
        ntdll = self.root / NTDLL_RELATIVE
        ntdll.parent.mkdir(parents=True)
        ntdll.write_bytes(b"x" * PATCHED_NTDLL_SIZE)

    def tearDown(self):
        self.temporary.cleanup()

    def test_path_is_versioned_separately_from_the_locked_base(self):
        self.assertEqual(
            self.root,
            self.paths.tools / "wine-test-msclassic1",
        )

    def test_v1_build_is_limited_to_the_validated_ubuntu_home(self):
        self.assertEqual(PATCHED_BUILD_CACHE, Path("/home/ubuntu/.cache/msclassic-build"))
        self.assertFalse(patched_runtime_build_supported(self.paths))
        supported = AppPaths.from_environment({"HOME": "/home/ubuntu"})
        self.assertTrue(patched_runtime_build_supported(supported))

    def test_requires_both_stamps_and_exact_patched_ntdll(self):
        expected_digest = hashlib.sha256(b"x" * PATCHED_NTDLL_SIZE).hexdigest()
        with mock.patch("msclassic.runtime.PATCHED_NTDLL_SHA256", expected_digest):
            (self.root / PATCH_STAMP).write_text(
                json.dumps(patched_runtime_manifest(self.artifact)), encoding="utf-8"
            )
            self.assertTrue(patched_runtime_valid(self.paths, self.artifact))

            (self.root / PATCH_STAMP).write_text("{}", encoding="utf-8")
            self.assertFalse(patched_runtime_valid(self.paths, self.artifact))
            (self.root / PATCH_STAMP).write_text(
                json.dumps(patched_runtime_manifest(self.artifact)), encoding="utf-8"
            )
            (self.root / NTDLL_RELATIVE).write_bytes(b"changed")
            self.assertFalse(patched_runtime_valid(self.paths, self.artifact))
