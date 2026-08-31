import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "platforms/proxmox/readonly-preflight.sh"


class ProxmoxReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.config = self.root / "qemu-server"
        self.config.mkdir()
        (self.config / "80001.conf").write_text(
            "name: Brad-Lubuntu-MS\nvga: virtio-gl\nmachine: q35\nbios: ovmf\n",
            encoding="utf-8",
        )
        self.render = self.root / "renderD128"
        self.render.touch()
        self.server = self.root / "virgl_render_server"
        self.server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.server.chmod(0o700)
        self.marker = self.root / "mutation-ran"
        self._command(
            "pveversion",
            '#!/bin/sh\nprintf "%s\\n" "${PVE_FAKE_VERSION:-pve-manager/9.2.3/test}"\n',
        )
        self._command(
            "qm",
            '#!/bin/sh\n'
            'if [ "$1" = status ]; then printf "status: %s\\n" "${PVE_FAKE_STATUS:-stopped}"; exit 0; fi\n'
            ': > "$PVE_MUTATION_MARKER"\nexit 99\n',
        )
        self._command(
            "lspci",
            "#!/bin/sh\nprintf 'Intel Arrow Lake-S VGA\\nKernel driver in use: i915\\n'\n",
        )
        self._command(
            "kvm",
            '#!/bin/sh\nprintf "%s\\n" "${PVE_FAKE_QEMU_HELP:-hostmem blob venus}"\n',
        )
        self._command(
            "dpkg-query",
            '#!/bin/sh\nprintf "%s" "${PVE_FAKE_PACKAGE_STATUS:-ii}"\n',
        )
        self.environment = os.environ | {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "PVE_CONF_DIR": str(self.config),
            "PVE_RENDER_NODE": str(self.render),
            "PVE_VIRGL_RENDER_SERVER": str(self.server),
            "PVE_MUTATION_MARKER": str(self.marker),
        }

    def tearDown(self):
        self.temp.cleanup()

    def _command(self, name, content):
        path = self.bin / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o700)

    def run_script(self, *arguments, **environment):
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            env=self.environment | environment,
            check=False,
        )

    def test_check_accepts_supported_pve_versions_without_mutation(self):
        for version in ("pve-manager/9.1.9/test", "pve-manager/9.2.3/test"):
            with self.subTest(version=version):
                result = self.run_script("check", "80001", PVE_FAKE_VERSION=version)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("read-only", result.stdout)
                self.assertFalse(self.marker.exists())

    def test_running_vm_and_existing_custom_args_are_rejected(self):
        result = self.run_script("check", "80001", PVE_FAKE_STATUS="running")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be stopped", result.stderr)

        (self.config / "80001.conf").write_text(
            "vga: virtio-gl\nargs: -set device.vga.blob=on\n",
            encoding="utf-8",
        )
        result = self.run_script("check", "80001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("custom args", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_host_capability_or_package_is_rejected(self):
        result = self.run_script("check", "80001", PVE_FAKE_QEMU_HELP="hostmem blob")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Venus", result.stderr)
        result = self.run_script("check", "80001", PVE_FAKE_PACKAGE_STATUS="un")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mesa-vulkan-drivers", result.stderr)

    def test_webui_plan_prints_but_never_executes_vm_scoped_commands(self):
        result = self.run_script("webui-plan", "80001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Proxmox WebUI", result.stdout)
        self.assertIn("Backup now", result.stdout)
        self.assertIn("qm set 80001 --args", result.stdout)
        self.assertIn("hostmem=2G", result.stdout)
        self.assertIn("blob=on", result.stdout)
        self.assertIn("venus=on", result.stdout)
        self.assertIn("No command below has been executed", result.stdout)
        self.assertFalse(self.marker.exists())

    def test_no_apply_or_rollback_subcommand_exists(self):
        for command in ("apply", "rollback"):
            result = self.run_script(command, "80001")
            self.assertEqual(result.returncode, 2)
            self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
