import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths
from msclassic.updater import (
    UPDATE_HEADROOM_BYTES,
    UpdaterError,
    apply_update,
    check_update,
    parse_update_json,
    stop_prefix,
)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})
        self.paths.client.mkdir(parents=True)
        payload = b"pinned-nxdl"
        self.artifact = Artifact(
            name="nxdl",
            version="v0.1.2-test",
            url="https://example.invalid/nxdl",
            algorithm="sha256",
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        self.nxdl = self.paths.tools / "nxdl-v0.1.2-test" / "nxdl"
        self.nxdl.parent.mkdir(parents=True)
        self.nxdl.write_bytes(payload)
        self.nxdl.chmod(0o700)

    def tearDown(self):
        self.temp.cleanup()

    def test_parses_one_exact_json_object_and_rejects_bad_sizes(self):
        value = parse_update_json(json.dumps({"total_size": 123, "files_to_download": 2}))
        self.assertEqual(value, 123)
        for bad in (
            "not json",
            "[]",
            "{}",
            '{"total_size": -1}',
            '{"total_size": true}',
            '{"total_size": 999999999999999}',
            '{"total_size": 1}\n{"total_size": 2}',
        ):
            with self.subTest(bad=bad), self.assertRaises(UpdaterError):
                parse_update_json(bad)

    def test_check_uses_exact_nxdl_argv_and_requires_headroom(self):
        completed = subprocess.CompletedProcess([], 0, '{"total_size":1048576}', "")
        usage = shutil._ntuple_diskusage(total=20 << 30, used=10 << 30, free=10 << 30)
        with mock.patch("msclassic.updater.subprocess.run", return_value=completed) as invoked:
            with mock.patch("msclassic.updater.shutil.disk_usage", return_value=usage):
                result = check_update(self.paths, self.artifact)

        self.assertTrue(result.allowed)
        self.assertEqual(result.total_size, 1048576)
        self.assertEqual(result.available, 10 << 30)
        self.assertEqual(
            invoked.call_args.args[0],
            [str(self.nxdl), "tms_cw", "--check", "--json"],
        )
        low = shutil._ntuple_diskusage(total=2 << 30, used=1 << 30, free=1048576 + UPDATE_HEADROOM_BYTES - 1)
        with mock.patch("msclassic.updater.subprocess.run", return_value=completed):
            with mock.patch("msclassic.updater.shutil.disk_usage", return_value=low):
                self.assertFalse(check_update(self.paths, self.artifact).allowed)

    def test_checksum_writability_and_active_launch_are_hard_gates(self):
        self.nxdl.write_bytes(b"changed")
        with mock.patch("msclassic.updater.subprocess.run") as invoked:
            with self.assertRaises(UpdaterError):
                check_update(self.paths, self.artifact)
            invoked.assert_not_called()
        self.nxdl.write_bytes(b"pinned-nxdl")

        self.paths.state.mkdir(parents=True)
        lock_path = self.paths.state / "launch.lock"
        lock_path.touch(mode=0o600)
        with lock_path.open("r+") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(UpdaterError):
                check_update(self.paths, self.artifact)

        with mock.patch("msclassic.updater.os.access", return_value=False):
            with self.assertRaises(UpdaterError):
                check_update(self.paths, self.artifact)

    def test_apply_is_explicit_and_uses_exact_download_argv(self):
        check_result = subprocess.CompletedProcess([], 0, '{"total_size":1}', "")
        download_result = subprocess.CompletedProcess([], 0, "", "")
        usage = shutil._ntuple_diskusage(total=20 << 30, used=1 << 30, free=19 << 30)
        with mock.patch("msclassic.updater.subprocess.run", side_effect=[check_result, download_result]) as invoked:
            with mock.patch("msclassic.updater.shutil.disk_usage", return_value=usage):
                code = apply_update(self.paths, self.artifact)
        self.assertEqual(code, 0)
        self.assertEqual(
            invoked.call_args_list[1].args[0],
            [str(self.nxdl), "tms_cw", "--download", str(self.paths.client)],
        )

    def test_stop_requires_confirmation_and_uses_only_prefix_wineserver(self):
        wineserver = self.paths.tools / "wine-11.10-staging-tkg-amd64-wow64/bin/wineserver"
        wineserver.parent.mkdir(parents=True)
        wineserver.write_bytes(b"binary")
        wineserver.chmod(0o700)
        with self.assertRaises(UpdaterError):
            stop_prefix(self.paths, confirmed=False)

        completed = subprocess.CompletedProcess([], 0)
        with mock.patch("msclassic.updater.subprocess.run", return_value=completed) as invoked:
            self.assertEqual(stop_prefix(self.paths, confirmed=True), 0)
        commands = [call.args[0] for call in invoked.call_args_list]
        self.assertEqual(commands, [[str(wineserver), "-k"], [str(wineserver), "-w"]])
        self.assertTrue(all("pkill" not in " ".join(command) for command in commands))
        self.assertEqual(invoked.call_args_list[1].kwargs["timeout"], 15)


if __name__ == "__main__":
    unittest.main()

