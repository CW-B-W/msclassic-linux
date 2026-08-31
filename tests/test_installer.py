import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
import subprocess
from unittest import mock

from msclassic.doctor import GraphicsReport
from msclassic.installer import (
    MINIMUM_FREE_BYTES,
    INPUT_RUNTIME_HEADROOM_BYTES,
    InstallerError,
    UnsafeArchiveError,
    build_install_plan,
    execute_install,
    InstallAction,
    InstallPlan,
    _install_ngs_service,
    _execute_action,
    _prepare_patched_runtime,
    _prefix_initialized,
    _run_runtime,
    perform_install,
    package_command_prefix,
    validate_tar_archive,
)
from msclassic.lockfile import Artifact
from msclassic.paths import AppPaths
from msclassic.platforms import LUBUNTU_2404
from msclassic.runtime import patched_runtime_root


REQUIRED_CLIENT_FILES = (
    "Maplestory_Classic.exe",
    "UnityPlayer.dll",
    "GameAssembly.dll",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/grap-core64.aes",
    "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe",
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
        self.runtime_validation = mock.patch(
            "msclassic.installer.patched_runtime_valid", return_value=True
        )
        self.runtime_validation.start()

    def tearDown(self):
        self.runtime_validation.stop()
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
            source_bytes + self.artifact.size * 3 + MINIMUM_FREE_BYTES + INPUT_RUNTIME_HEADROOM_BYTES,
        )
        self.assertIn("import_client", [action.kind for action in plan.actions])
        kinds = [action.kind for action in plan.actions]
        self.assertLess(kinds.index("import_registry"), kinds.index("install_ngs"))

    def test_rejects_incomplete_source(self):
        (self.source / "UnityPlayer.dll").unlink()
        with self.assertRaises(InstallerError):
            build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)

    def test_install_prepares_input_runtime_before_any_prefix_execution(self):
        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        builds = [action for action in plan.actions if action.kind.startswith("prepare_")]
        self.assertEqual([action.destination.name for action in builds],
                         ["wine-test-msclassic1", "wine-test-msclassic2"])
        self.assertEqual(builds[1].source, builds[0].destination)
        self.assertLess(plan.actions.index(builds[1]),
                        next(i for i, action in enumerate(plan.actions) if action.kind == "initialize_prefix"))

    def test_input_runtime_build_uses_verified_base_and_validates_result(self):
        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        action = next(a for a in plan.actions if a.kind == "prepare_patched_runtime")
        with (
            mock.patch("msclassic.installer.patched_runtime_valid", side_effect=[False, True]),
            mock.patch("msclassic.installer.base_runtime_valid", return_value=True),
            mock.patch("msclassic.installer.patched_runtime_build_supported", return_value=True),
            mock.patch("msclassic.installer.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as build,
        ):
            _prepare_patched_runtime(action, self.paths)
        self.assertEqual(build.call_args.args[0], [
            str(REPO / "scripts/build-input-wine.sh"),
            "--base-runtime", str(self.paths.tools / "wine-test-msclassic1"),
            "--output", str(self.paths.tools / "wine-test-msclassic2"),
            "--cache", "/home/ubuntu/.cache/msclassic-build",
        ])
        self.assertFalse(build.call_args.kwargs["shell"])
        with (
            mock.patch("msclassic.installer.patched_runtime_valid", return_value=False),
            mock.patch("msclassic.installer.base_runtime_valid", return_value=False),
            mock.patch("msclassic.installer.subprocess.run") as build,
        ):
            with self.assertRaisesRegex(InstallerError, "verified base"):
                _prepare_patched_runtime(action, self.paths)
            build.assert_not_called()

    def test_rejects_source_without_vendor_ngs_installer(self):
        (
            self.source
            / "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe"
        ).unlink()
        with self.assertRaises(InstallerError):
            build_install_plan(
                self.paths,
                {"wine": self.artifact},
                self.source,
                LUBUNTU_2404,
            )

    def test_failed_or_unverified_input_build_stops_before_prefix_execution(self):
        plan = build_install_plan(self.paths, {"wine": self.artifact}, self.source, LUBUNTU_2404)
        build = next(a for a in plan.actions if a.kind == "prepare_patched_runtime")
        remaining = InstallPlan((build, InstallAction("initialize_prefix")), 0)
        for returncode in (1, 0):
            with (
                self.subTest(returncode=returncode),
                mock.patch("msclassic.installer.patched_runtime_valid", return_value=False),
                mock.patch("msclassic.installer.base_runtime_valid", return_value=True),
                mock.patch("msclassic.installer.patched_runtime_build_supported", return_value=True),
                mock.patch("msclassic.installer.subprocess.run",
                           return_value=subprocess.CompletedProcess([], returncode)) as invoked,
                mock.patch("msclassic.installer._run_runtime") as prefix,
            ):
                with self.assertRaisesRegex(InstallerError, "failed verification"):
                    execute_install(remaining, self._report(passes=True), False,
                                    operation=lambda action: _execute_action(action, self.paths, REPO / "prefix.reg"))
                invoked.assert_called_once()
                prefix.assert_not_called()

    def test_download_mode_acquires_only_after_locked_nxdl_is_installed(self):
        nxdl = Artifact(
            "nxdl",
            "v0.1.2-prerelease3",
            "https://example.invalid/nxdl",
            "sha256",
            hashlib.sha256(b"nxdl").hexdigest(),
            4,
        )

        plan = build_install_plan(
            self.paths,
            {"wine": self.artifact, "nxdl": nxdl},
            None,
            LUBUNTU_2404,
            download_client=True,
        )

        kinds = [action.kind for action in plan.actions]
        self.assertIn("acquire_client", kinds)
        self.assertLess(kinds.index("install_binary"), kinds.index("acquire_client"))
        self.assertLess(kinds.index("acquire_client"), kinds.index("initialize_prefix"))
        self.assertNotIn("import_client", kinds)
        self.assertEqual(
            next(action for action in plan.actions if action.kind == "acquire_client").artifact,
            nxdl,
        )

    def test_download_mode_reuses_valid_client_and_refuses_invalid_client(self):
        nxdl = Artifact(
            "nxdl",
            "v0.1.2-prerelease3",
            "https://example.invalid/nxdl",
            "sha256",
            hashlib.sha256(b"nxdl").hexdigest(),
            4,
        )
        for relative in REQUIRED_CLIENT_FILES:
            destination = self.paths.client / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((self.source / relative).read_bytes())

        reused = build_install_plan(
            self.paths,
            {"wine": self.artifact, "nxdl": nxdl},
            None,
            LUBUNTU_2404,
            download_client=True,
        )
        self.assertIn("verify_client", [action.kind for action in reused.actions])
        self.assertNotIn("acquire_client", [action.kind for action in reused.actions])

        (self.paths.client / "UnityPlayer.dll").unlink()
        (self.paths.client / "UnityPlayer.dll").symlink_to(
            self.source / "UnityPlayer.dll"
        )
        with self.assertRaisesRegex(InstallerError, "existing client is invalid"):
            build_install_plan(
                self.paths,
                {"wine": self.artifact, "nxdl": nxdl},
                None,
                LUBUNTU_2404,
                download_client=True,
            )

        shutil.rmtree(self.paths.client)
        self.paths.client.symlink_to(self.root / "missing-client", target_is_directory=True)
        with self.assertRaisesRegex(InstallerError, "existing client is invalid"):
            build_install_plan(
                self.paths,
                {"wine": self.artifact, "nxdl": nxdl},
                None,
                LUBUNTU_2404,
                download_client=True,
            )

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
        runtime = patched_runtime_root(self.paths, artifact)
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
        (self.paths.prefix / "user.reg").write_text(
            "WINE REGISTRY Version 2\n", encoding="utf-8"
        )
        (self.paths.prefix / "drive_c/windows/system32").mkdir(parents=True)
        (self.paths.prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n",
            encoding="utf-8",
        )
        timed_out = subprocess.TimeoutExpired([str(runtime / "bin/wineboot")], 60)
        completed = subprocess.CompletedProcess([], 0)

        with mock.patch("msclassic.installer.subprocess.run", side_effect=[timed_out, completed, completed]) as invoked:
            _run_runtime(self.paths, ["wineboot", "-u"])

        commands = [call.args[0] for call in invoked.call_args_list]
        self.assertEqual(commands[0], [str(runtime / "bin/wineboot"), "-u"])
        self.assertEqual(commands[1:], [[str(runtime / "bin/wineserver"), "-k"], [str(runtime / "bin/wineserver"), "-w"]])
        self.assertEqual(invoked.call_args_list[0].kwargs["timeout"], 60)
        self.assertEqual(
            invoked.call_args_list[0].kwargs["env"]["WINEDLLOVERRIDES"],
            "mscoree,mshtml=",
        )

    def test_wineboot_timeout_rejects_incomplete_prefix(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = patched_runtime_root(self.paths, artifact)
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

    def test_wineboot_success_flushes_server_before_accepting_prefix(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = patched_runtime_root(self.paths, artifact)
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
        (self.paths.prefix / "user.reg").write_text(
            "WINE REGISTRY Version 2\n", encoding="utf-8"
        )
        (self.paths.prefix / "drive_c/windows/system32").mkdir(parents=True)

        def fake_run(argv, **kwargs):
            if argv == [str(runtime / "bin/wineserver"), "-w"]:
                (self.paths.prefix / "system.reg").write_text(
                    "WINE REGISTRY Version 2\n"
                    "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
                    "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n",
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch("msclassic.installer.subprocess.run", side_effect=fake_run) as invoked:
            _run_runtime(self.paths, ["wineboot", "-u"])

        self.assertEqual(
            [call.args[0] for call in invoked.call_args_list],
            [
                [str(runtime / "bin/wineboot"), "-u"],
                [str(runtime / "bin/wineserver"), "-k"],
                [str(runtime / "bin/wineserver"), "-w"],
            ],
        )

    def test_prefix_completion_requires_wine_rpc_and_plugplay_services(self):
        prefix = self.root / "prefix-completion"
        (prefix / "drive_c/windows/system32").mkdir(parents=True)
        (prefix / "user.reg").write_text("WINE REGISTRY Version 2\n", encoding="utf-8")
        (prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\MountMgr] 1\n",
            encoding="utf-8",
        )

        self.assertFalse(_prefix_initialized(prefix))

        (prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\MountMgr] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n",
            encoding="utf-8",
        )

        self.assertTrue(_prefix_initialized(prefix))

    def test_ngs_installer_uses_exact_vendor_command_and_verifies_flushed_state(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = patched_runtime_root(self.paths, artifact)
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
        ngs = (
            self.paths.client
            / "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe"
        )
        ngs.parent.mkdir(parents=True)
        ngs.write_bytes(b"MZ")
        self.paths.prefix.mkdir(parents=True)
        (self.paths.prefix / "user.reg").write_text(
            "WINE REGISTRY Version 2\n", encoding="utf-8"
        )
        (self.paths.prefix / "drive_c/windows/system32").mkdir(parents=True)
        (self.paths.prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n",
            encoding="utf-8",
        )

        def fake_run(argv, **kwargs):
            if argv == [str(runtime / "bin/wineserver"), "-w"]:
                with (self.paths.prefix / "system.reg").open("a", encoding="utf-8") as stream:
                    stream.write("[System\\\\ControlSet001\\\\Services\\\\NGS] 1\n")
                broker = (
                    self.paths.prefix
                    / "drive_c/ProgramData/Nexon/NGS/NGService.exe"
                )
                broker.parent.mkdir(parents=True)
                broker.write_bytes(b"MZ")
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch("msclassic.installer.subprocess.run", side_effect=fake_run) as invoked:
            _install_ngs_service(self.paths, ngs)

        calls = invoked.call_args_list
        self.assertEqual(
            calls[0].args[0],
            [str(runtime / "bin/wine"), str(ngs), "-install"],
        )
        self.assertEqual(calls[0].kwargs["cwd"], ngs.parent)
        self.assertFalse(calls[0].kwargs["shell"])
        self.assertEqual(calls[0].kwargs["env"]["WINEPREFIX"], str(self.paths.prefix))
        self.assertEqual(
            calls[0].kwargs["env"]["WINEDLLOVERRIDES"],
            "mscoree,mshtml=",
        )
        self.assertEqual(
            [call.args[0] for call in calls[1:]],
            [
                [str(runtime / "bin/wineserver"), "-k"],
                [str(runtime / "bin/wineserver"), "-w"],
            ],
        )

    def test_ngs_installer_rejects_success_exit_without_persistent_service_state(self):
        from msclassic.lockfile import load_versions

        artifact = load_versions(REPO / "versions.lock")["wine"]
        runtime = patched_runtime_root(self.paths, artifact)
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
        ngs = (
            self.paths.client
            / "Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe"
        )
        ngs.parent.mkdir(parents=True)
        ngs.write_bytes(b"MZ")
        self.paths.prefix.mkdir(parents=True)
        (self.paths.prefix / "user.reg").write_text(
            "WINE REGISTRY Version 2\n", encoding="utf-8"
        )
        (self.paths.prefix / "drive_c/windows/system32").mkdir(parents=True)
        (self.paths.prefix / "system.reg").write_text(
            "WINE REGISTRY Version 2\n"
            "[System\\\\ControlSet001\\\\Services\\\\PlugPlay] 1\n"
            "[System\\\\ControlSet001\\\\Services\\\\RpcSs] 1\n",
            encoding="utf-8",
        )
        completed = subprocess.CompletedProcess([], 0)

        with mock.patch("msclassic.installer.subprocess.run", return_value=completed):
            with self.assertRaises(InstallerError):
                _install_ngs_service(self.paths, ngs)

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

    def test_guest_wrapper_download_dry_run_is_explicit_and_zero_mutation(self):
        env = os.environ.copy()
        env.update({"HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"})
        command = [
            "bash",
            str(REPO / "platforms/lubuntu-24.04/install.sh"),
            "--dry-run",
            "--download-client",
        ]
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN: zero mutations", result.stdout)
        self.assertIn("acquire_client", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])
        no_mode = subprocess.run(
            command[:2] + ["--dry-run"],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(no_mode.returncode, 2)

    def test_docs_cover_first_time_download_and_staging_recovery(self):
        quick_start = (REPO / "docs/quick-start-lubuntu-pve.md").read_text(
            encoding="utf-8"
        )
        readme = (REPO / "README.md").read_text(encoding="utf-8")

        self.assertIn("install.sh --download-client", quick_start)
        self.assertIn(".MapleStoryClassic.download", quick_start)
        self.assertIn("--download-client", readme)

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
