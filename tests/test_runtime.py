import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths
from msclassic.runtime import (
    DIAGNOSTIC_IMM32_RELATIVE,
    DIAGNOSTIC_STAMP,
    DIAGNOSTIC_WINEX11_RELATIVE,
    diagnostic_runtime_manifest,
    diagnostic_runtime_root,
    diagnostic_runtime_valid,
    PATCHED_BUILD_CACHE,
    NTDLL_RELATIVE,
    PATCHED_NTDLL_SIZE,
    PATCH_STAMP,
    patched_runtime_manifest,
    patched_runtime_build_supported,
    patched_runtime_root,
    patched_runtime_valid,
    base_runtime_root,
    base_runtime_valid,
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
        self.root = base_runtime_root(self.paths, self.artifact)
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
        self.assertEqual(patched_runtime_root(self.paths, self.artifact),
                         self.paths.tools / "wine-test-msclassic2")

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
            self.assertTrue(base_runtime_valid(self.paths, self.artifact))
            self.assertFalse(patched_runtime_valid(self.paths, self.artifact))

            (self.root / PATCH_STAMP).write_text("{}", encoding="utf-8")
            self.assertFalse(base_runtime_valid(self.paths, self.artifact))
            (self.root / PATCH_STAMP).write_text(
                json.dumps(patched_runtime_manifest(self.artifact)), encoding="utf-8"
            )
            (self.root / NTDLL_RELATIVE).write_bytes(b"changed")
            self.assertFalse(base_runtime_valid(self.paths, self.artifact))

    def test_normal_runtime_requires_exact_input_modules_and_ntdll(self):
        diagnostic = diagnostic_runtime_root(self.paths, self.artifact)
        shutil.copytree(self.root, diagnostic)
        driver = diagnostic / DIAGNOSTIC_WINEX11_RELATIVE
        driver.parent.mkdir(parents=True, exist_ok=True)
        driver.write_bytes(b"diagnostic-driver")
        imm32 = diagnostic / DIAGNOSTIC_IMM32_RELATIVE
        imm32.parent.mkdir(parents=True, exist_ok=True)
        imm32.write_bytes(b"diagnostic-imm32")
        expected_ntdll = hashlib.sha256(b"x" * PATCHED_NTDLL_SIZE).hexdigest()
        expected_driver = hashlib.sha256(b"diagnostic-driver").hexdigest()
        expected_imm32 = hashlib.sha256(b"diagnostic-imm32").hexdigest()

        with (
            mock.patch("msclassic.runtime.PATCHED_NTDLL_SHA256", expected_ntdll),
            mock.patch("msclassic.runtime.DIAGNOSTIC_WINEX11_SHA256", expected_driver),
            mock.patch("msclassic.runtime.DIAGNOSTIC_WINEX11_SIZE", len(b"diagnostic-driver")),
            mock.patch("msclassic.runtime.DIAGNOSTIC_IMM32_SHA256", expected_imm32),
            mock.patch("msclassic.runtime.DIAGNOSTIC_IMM32_SIZE", len(b"diagnostic-imm32")),
        ):
            (diagnostic / PATCH_STAMP).write_text(
                json.dumps(patched_runtime_manifest(self.artifact)), encoding="utf-8"
            )
            (diagnostic / DIAGNOSTIC_STAMP).write_text(
                json.dumps(diagnostic_runtime_manifest(self.artifact)), encoding="utf-8"
            )
            self.assertEqual(
                diagnostic,
                self.paths.tools / "wine-test-msclassic2",
            )
            self.assertTrue(diagnostic_runtime_valid(self.paths, self.artifact))
            self.assertTrue(patched_runtime_valid(self.paths, self.artifact))

            driver.write_bytes(b"changed")
            self.assertFalse(diagnostic_runtime_valid(self.paths, self.artifact))
            self.assertFalse(patched_runtime_valid(self.paths, self.artifact))
            driver.write_bytes(b"diagnostic-driver")
            imm32.write_bytes(b"changed")
            self.assertFalse(diagnostic_runtime_valid(self.paths, self.artifact))
