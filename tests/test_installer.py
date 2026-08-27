import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
import subprocess
from unittest import mock

from msclassic.doctor import GraphicsReport
from msclassic.installer import (
    MINIMUM_FREE_BYTES,
    InstallerError,
    UnsafeArchiveError,
    build_install_plan,
    execute_install,
    InstallAction,
    InstallPlan,
    _run_runtime,
    perform_install,
    package_command_prefix,
    validate_tar_archive,
)
from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths
from msclassic.platforms import LUBUNTU_2404


REQUIRED_CLIENT_FILES = (
    "Maplestory_Classic.exe",
    "UnityPlayer.dll",
    "GameAssembly.dll",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes",
)
REPO = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment({"HOME": str(self.home)})
        self.source = self.root / "source"
        self.source.mkdir()
        for index, relative in enumerate(REQUIRED_CLIENT_FILES, start=1):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes([index]) * index)
        payload = b"locked-artifact"
        self.artifact = Artifact(
            name="wine",
            version="wine-test",
            url="https://example.invalid/wine.tar",
            algorithm="sha256",
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        self.payload = payload

    def tearDown(self):
        self.temp.cleanup()

    def _report(self, *, passes: bool) -> GraphicsReport:
        return GraphicsReport(
            kernel="6.17.0",
            session="x11",
            resolution=(1366, 768),
            drm_nodes=("/dev/dri/renderD128",),
            render_access=True,
            opengl_renderer="virgl" if passes else "llvmpipe",
            vulkan_devices=(
                {"name": "Virtio-GPU Venus Intel", "driver": "venus", "type": "DISCRETE_GPU"},
            ),
            selected_device="Virtio-GPU Venus Intel" if passes else "llvmpipe",
            packages={
                "libvulkan1:i386": "1",
                "mesa-vulkan-drivers:i386": "1",
            },
            boot_id="boot-a",
        )

    def test_plan_accepts_read_only_source_and_has_exact_packages_and_space(self):
        for directory, subdirs, files in os.walk(self.source):
            Path(directory).chmod(0o555)
            for name in files:
                (Path(directory) / name).chmod(0o444)

        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)

        package_action = plan.actions[0]
        self.assertEqual(package_action.kind, "install_packages")
        self.assertEqual(package_action.values, LUBUNTU_2404.package_names)
        source_bytes = sum((self.source / item).stat().st_size for item in REQUIRED_CLIENT_FILES)
        self.assertEqual(
            plan.required_bytes,
            source_bytes + self.artifact.size * 3 + MINIMUM_FREE_BYTES,
        )
        self.assertIn("import_client", [action.kind for action in plan.actions])

    def test_rejects_incomplete_source(self):
        (self.source / "UnityPlayer.dll").unlink()
        with self.assertRaises(InstallerError):
            build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)

    def test_existing_destination_is_verified_or_backed_up_before_import(self):
        self.paths.client.mkdir(parents=True)
        (self.paths.client / "unrelated.txt").write_text("keep", encoding="utf-8")

        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        kinds = [action.kind for action in plan.actions]

        self.assertLess(kinds.index("backup_client"), kinds.index("import_client"))
        for relative in REQUIRED_CLIENT_FILES:
            destination = self.paths.client / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.source / relative).read_bytes())
        second = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        self.assertIn("verify_client", [action.kind for action in second.actions])
        self.assertNotIn("import_client", [action.kind for action in second.actions])

    def test_cache_is_reused_only_after_checksum_or_quarantined(self):
        cached = self.paths.cache / "downloads" / "wine.tar"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(self.payload)
        valid = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        self.assertIn("reuse_artifact", [action.kind for action in valid.actions])
        self.assertNotIn("download_artifact", [action.kind for action in valid.actions])
        extraction = next(action for action in valid.actions if action.kind == "extract_artifact")
        self.assertEqual(extraction.destination, self.paths.tools / "wine-test")

        cached.write_bytes(b"wrong")
        invalid = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        kinds = [action.kind for action in invalid.actions]
        self.assertLess(kinds.index("quarantine_artifact"), kinds.index("download_artifact"))

    def test_locked_nxdl_install_path_matches_updater_lookup(self):
        nxdl = Artifact(
            "nxdl",
            "v0.1.2-prerelease3",
            "https://example.invalid/nxdl",
            "sha256",
            hashlib.sha256(b"nxdl").hexdigest(),
            4,
        )
        plan = build_install_plan(self.paths, {"nxdl": nxdl}, self.source, LUBUNTU_2404)
        action = next(item for item in plan.actions if item.kind == "install_binary")
        self.assertEqual(
            action.destination,
            self.paths.tools / "nxdl-v0.1.2-prerelease3/nxdl",
        )

    def test_locked_wine_path_matches_launcher_lookup(self):
        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)

        action = next(item for item in plan.actions if item.kind == "extract_artifact")
        self.assertEqual(action.destination, self.paths.tools / "wine-test")

    def test_wineboot_timeout_accepts_verified_prefix_and_stops_only_its_server(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = self.paths.tools / artifact.version
        (runtime / "bin").mkdir(parents=True)
        for name in ("wine", "wineserver", "wineboot", "regedit"):
            tool = runtime / "bin" / name
            tool.write_bytes(b"tool")
            tool.chmod(0o700)
        (runtime / ".msclassic-artifact.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": artifact.name,
                    "version": artifact.version,
                    "digest": artifact.digest,
                }
            ),
            encoding="utf-8",
        )
        self.paths.prefix.mkdir(parents=True)
        (self.paths.prefix / "system.reg").write_text("registry", encoding="utf-8")
        (self.paths.prefix / "user.reg").write_text("registry", encoding="utf-8")
        (self.paths.prefix / "drive_c/windows/system32").mkdir(parents=True)
        timed_out = subprocess.TimeoutExpired([str(runtime / "bin/wineboot")], 60)
        completed = subprocess.CompletedProcess([], 0)

        with mock.patch("msclassic.installer.subprocess.run", side_effect=[timed_out, completed, completed]) as invoked:
            _run_runtime(self.paths, ["wineboot", "-u"])

        commands = [call.args[0] for call in invoked.call_args_list]
        self.assertEqual(commands[0], [str(runtime / "bin/wineboot"), "-u"])
        self.assertEqual(commands[1:], [[str(runtime / "bin/wineserver"), "-k"], [str(runtime / "bin/wineserver"), "-w"]])
        self.assertEqual(invoked.call_args_list[0].kwargs["timeout"], 60)

    def test_wineboot_timeout_rejects_incomplete_prefix(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = self.paths.tools / artifact.version
        (runtime / "bin").mkdir(parents=True)
        for name in ("wine", "wineserver", "wineboot", "regedit"):
            tool = runtime / "bin" / name
            tool.write_bytes(b"tool")
            tool.chmod(0o700)
        (runtime / ".msclassic-artifact.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": artifact.name,
                    "version": artifact.version,
                    "digest": artifact.digest,
                }
            ),
            encoding="utf-8",
        )
        timed_out = subprocess.TimeoutExpired([str(runtime / "bin/wineboot")], 60)
        completed = subprocess.CompletedProcess([], 0)

        with mock.patch("msclassic.installer.subprocess.run", side_effect=[timed_out, completed, completed]):
            with self.assertRaises(InstallerError):
                _run_runtime(self.paths, ["wineboot", "-u"])

    def test_rejects_unrecognized_runtime_artifacts(self):
        unknown = Artifact(
            "unknown",
            "1.0",
            "https://example.invalid/unknown.tar",
            "sha256",
            hashlib.sha256(b"unknown").hexdigest(),
            7,
        )

        with self.assertRaises(InstallerError):
            build_install_plan(self.paths, {"unknown": unknown}, self.source, LUBUNTU_2404)

    def test_tar_validation_rejects_traversal_devices_and_escaping_links(self):
        unsafe_names = ("/absolute", "../escape")
        for name in unsafe_names:
            archive = self._archive(name=name)
            with self.assertRaises(UnsafeArchiveError):
                validate_tar_archive(archive)

        device = tarfile.TarInfo("device")
        device.type = tarfile.CHRTYPE
        with self.assertRaises(UnsafeArchiveError):
            validate_tar_archive(self._archive(member=device))
        link = tarfile.TarInfo("safe/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../escape"
        with self.assertRaises(UnsafeArchiveError):
            validate_tar_archive(self._archive(member=link))

        validate_tar_archive(self._archive(name="runtime/bin/wine"))

    def test_extract_flattens_single_upstream_root_into_versioned_directory(self):
        payload_root = self.root / "payload/wine-test/bin"
        payload_root.mkdir(parents=True)
        (payload_root / "wine").write_text("runner", encoding="utf-8")
        (payload_root / "wineserver").write_text("server", encoding="utf-8")
        archive = self.root / "wine-real-layout.tar"
        with tarfile.open(archive, "w") as bundle:
            bundle.add(payload_root.parent, arcname="wine-test")
        artifact = Artifact(
            "wine",
            "wine-test",
            "https://example.invalid/wine.tar",
            "sha256",
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            archive.stat().st_size,
        )
        destination = self.paths.tools / "wine-test"
        plan = InstallPlan(
            (InstallAction("extract_artifact", ("wine", "wine-test"), archive, destination, artifact),),
            0,
        )

        perform_install(plan, self._report(passes=True), self.paths, self.root / "unused.reg")

        self.assertTrue((destination / "bin/wine").is_file())
        self.assertTrue((destination / "bin/wineserver").is_file())
        self.assertFalse((destination / "wine-test/bin/wine").exists())

    def test_dry_run_never_calls_executor_and_real_install_requires_graphics(self):
        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        operation = mock.Mock(side_effect=AssertionError("must not run"))
        result = execute_install(plan, self._report(passes=False), dry_run=True, operation=operation)
        self.assertFalse(result.mutated)
        operation.assert_not_called()

        with self.assertRaises(InstallerError):
            execute_install(plan, self._report(passes=False), dry_run=False, operation=operation)
        operation.assert_not_called()

    def test_package_authority_requires_root_or_sudo(self):
        self.assertEqual(package_command_prefix(euid=0, sudo_path=None), ())
        self.assertEqual(package_command_prefix(euid=1000, sudo_path="/usr/bin/sudo"), ("/usr/bin/sudo",))
        with self.assertRaises(InstallerError):
            package_command_prefix(euid=1000, sudo_path=None)

    def test_registry_is_narrowly_scoped_and_has_no_anti_cheat_overrides(self):
        registry = (REPO / "platforms/lubuntu-24.04/maplestory-classic.reg").read_text(encoding="utf-8")
        self.assertIn("Maplestory_Classic.exe", registry)
        self.assertIn('"Version"="win10"', registry)
        self.assertIn('"UseLinuxInputEvents"="Y"', registry)
        self.assertIn('"KeyboardUseNonExclusive"="Y"', registry)
        self.assertIn('"MouseUseNonExclusive"="Y"', registry)
        self.assertIn('"UseTakeFocus"="N"', registry)
        self.assertIn('"Grab"="N"', registry)
        self.assertIn('"GrabFullscreen"="N"', registry)
        lowered = registry.lower()
        self.assertNotIn("dlloverrides", lowered)
        self.assertNotIn("grap", lowered)
        self.assertNotIn("ngs", lowered)

    def test_guest_wrapper_dry_run_makes_no_home_changes(self):
        env = os.environ.copy()
        env.update({"HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})
        result = subprocess.run(
            ["bash", str(REPO / "platforms/lubuntu-24.04/install.sh"), "--dry-run", "--source", str(self.source)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN: zero mutations", result.stdout)
        self.assertIn("wine-11.10-staging-tkg-amd64-wow64", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def _archive(self, *, name=None, member=None):
        path = self.root / f"archive-{len(list(self.root.glob('archive-*')))}.tar"
        info = member or tarfile.TarInfo(name)
        if info.isreg():
            info.size = 1
        with tarfile.open(path, "w") as archive:
            archive.addfile(info, io.BytesIO(b"x") if info.isreg() else None)
        return path


if __name__ == "__main__":
    unittest.main()

