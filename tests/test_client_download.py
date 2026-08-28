import fcntl
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.client_download import (
    DOWNLOAD_HEADROOM_BYTES,
    ClientDownloadError,
    check_download,
    download_and_promote,
    normalize_windows_backslash_names,
)
from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths


REQUIRED_CLIENT_FILES = (
    "Maplestory_Classic.exe",
    "UnityPlayer.dll",
    "GameAssembly.dll",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe",
)


class ClientDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})
        payload = b"pinned-nxdl"
        self.artifact = Artifact(
            name="nxdl",
            version="v0.1.2-test",
            url="https://example.invalid/nxdl",
            algorithm="sha256",
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        self.nxdl = self.paths.tools / f"nxdl-{self.artifact.version}" / "nxdl"
        self.nxdl.parent.mkdir(parents=True)
        self.nxdl.write_bytes(payload)
        self.nxdl.chmod(0o700)
        self.stage = self.paths.client.with_name(".MapleStoryClassic.download")

    def tearDown(self):
        self.temp.cleanup()

    def test_check_uses_verified_nxdl_and_requires_manifest_headroom(self):
        completed = subprocess.CompletedProcess([], 0, '{"total_size":17}', "")
        high = shutil._ntuple_diskusage(total=10 << 30, used=1 << 30, free=9 << 30)
        with mock.patch(
            "msclassic.client_download.subprocess.run", return_value=completed
        ) as invoked:
            with mock.patch("msclassic.client_download.shutil.disk_usage", return_value=high):
                result = check_download(self.paths, self.artifact)

        self.assertTrue(result.allowed)
        self.assertEqual(result.total_size, 17)
        self.assertEqual(result.available, 9 << 30)
        self.assertEqual(
            invoked.call_args.args[0],
            [str(self.nxdl), "tms_cw", "--check", "--json"],
        )
        low = shutil._ntuple_diskusage(
            total=2 << 30,
            used=1 << 30,
            free=17 + DOWNLOAD_HEADROOM_BYTES - 1,
        )
        with mock.patch(
            "msclassic.client_download.subprocess.run", return_value=completed
        ):
            with mock.patch("msclassic.client_download.shutil.disk_usage", return_value=low):
                self.assertFalse(check_download(self.paths, self.artifact).allowed)

    def test_check_rejects_changed_binary_and_active_launch_without_spawning(self):
        self.nxdl.write_bytes(b"changed")
        with mock.patch("msclassic.client_download.subprocess.run") as invoked:
            with self.assertRaises(ClientDownloadError):
                check_download(self.paths, self.artifact)
            invoked.assert_not_called()
        self.nxdl.write_bytes(b"pinned-nxdl")

        self.paths.state.mkdir(parents=True)
        lock_path = self.paths.state / "launch.lock"
        lock_path.touch(mode=0o600)
        with lock_path.open("r+") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch("msclassic.client_download.subprocess.run") as invoked:
                with self.assertRaises(ClientDownloadError):
                    check_download(self.paths, self.artifact)
                invoked.assert_not_called()

    def test_download_normalizes_and_promotes_only_a_valid_client(self):
        usage = shutil._ntuple_diskusage(total=10 << 30, used=1 << 30, free=9 << 30)

        def fake_run(argv, **_kwargs):
            if argv[-2:] == ["--check", "--json"]:
                return subprocess.CompletedProcess(argv, 0, '{"total_size":1}', "")
            self._write_downloaded_client(Path(argv[-1]))
            return subprocess.CompletedProcess(argv, 0, "", "")

        with mock.patch("msclassic.client_download.subprocess.run", side_effect=fake_run) as invoked:
            with mock.patch("msclassic.client_download.shutil.disk_usage", return_value=usage):
                download_and_promote(self.paths, self.artifact, self._validate_client)

        self.assertTrue((self.paths.client / "Maplestory_Classic.exe").is_file())
        self.assertTrue(
            (
                self.paths.client
                / "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes"
            ).is_file()
        )
        self.assertFalse(self.stage.exists())
        self.assertEqual(
            invoked.call_args_list[1].args[0],
            [str(self.nxdl), "tms_cw", "--download", str(self.stage)],
        )

    def test_normalization_rejects_escape_collision_and_symlink(self):
        escape = self.root / "escape"
        escape.mkdir()
        (escape / "..\\outside").write_bytes(b"x")
        with self.assertRaises(ClientDownloadError):
            normalize_windows_backslash_names(escape)

        collision = self.root / "collision"
        (collision / "plugins").mkdir(parents=True)
        (collision / "plugins/core.aes").write_bytes(b"old")
        (collision / "plugins\\core.aes").write_bytes(b"new")
        with self.assertRaises(ClientDownloadError):
            normalize_windows_backslash_names(collision)

        linked = self.root / "linked"
        linked.mkdir()
        (linked / "unsafe").symlink_to(self.root / "escape")
        with self.assertRaises(ClientDownloadError):
            normalize_windows_backslash_names(linked)

    def test_invalid_final_client_is_never_replaced_and_failed_download_keeps_stage(self):
        self.paths.client.mkdir(parents=True)
        (self.paths.client / "keep").write_text("original", encoding="utf-8")
        with mock.patch("msclassic.client_download.subprocess.run") as invoked:
            with self.assertRaises(ClientDownloadError):
                download_and_promote(self.paths, self.artifact, self._validate_client)
            invoked.assert_not_called()
        self.assertEqual((self.paths.client / "keep").read_text(encoding="utf-8"), "original")

        (self.paths.client / "keep").unlink()
        self.paths.client.rmdir()
        self.stage.mkdir(parents=True)
        usage = shutil._ntuple_diskusage(total=10 << 30, used=1 << 30, free=9 << 30)
        check = subprocess.CompletedProcess([], 0, '{"total_size":1}', "")
        failed = subprocess.CompletedProcess([], 1, "", "")
        with mock.patch(
            "msclassic.client_download.subprocess.run", side_effect=[check, failed]
        ):
            with mock.patch("msclassic.client_download.shutil.disk_usage", return_value=usage):
                with self.assertRaises(ClientDownloadError):
                    download_and_promote(self.paths, self.artifact, self._validate_client)
        self.assertTrue(self.stage.is_dir())

    def _write_downloaded_client(self, stage):
        stage.mkdir(parents=True, exist_ok=True)
        for relative in REQUIRED_CLIENT_FILES:
            if relative.endswith("grap-core64.aes"):
                path = stage / relative.replace("/", "\\")
            else:
                path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def _validate_client(self, root):
        missing = [relative for relative in REQUIRED_CLIENT_FILES if not (root / relative).is_file()]
        if missing:
            raise ValueError("missing required files")


if __name__ == "__main__":
    unittest.main()
