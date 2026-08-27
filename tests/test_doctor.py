import unittest

from msclassic.doctor import (
    GraphicsReport,
    evaluate_launch_graphics,
    parse_active_resolution,
    parse_opengl_renderer,
    parse_vulkan_devices,
)


class GraphicsParserTests(unittest.TestCase):
    def test_parses_virgl_opengl_renderer(self):
        output = (
            "name of display: :0\n"
            "OpenGL renderer string: virgl (Mesa Intel(R) Graphics (ARL-S))\n"
        )
        self.assertEqual(
            parse_opengl_renderer(output),
            "virgl (Mesa Intel(R) Graphics (ARL-S))",
        )

    def test_parses_vulkan_as_diagnostic_data(self):
        output = (
            "GPU0:\n"
            "    deviceType = PHYSICAL_DEVICE_TYPE_CPU\n"
            "    deviceName = llvmpipe (LLVM 20.1.2)\n"
            "    driverName = lavapipe\n"
        )
        self.assertEqual(parse_vulkan_devices(output)[0]["driver"], "lavapipe")

    def test_parses_active_xrandr_resolution(self):
        output = "   1366x768      59.79*+  50.00\n   1280x720      60.00\n"
        self.assertEqual(parse_active_resolution(output), (1366, 768))


class GraphicsGateTests(unittest.TestCase):
    def report(self, **changes):
        values = {
            "kernel": "6.17.0-14-generic",
            "session": "x11",
            "resolution": (1366, 768),
            "drm_nodes": ("/dev/dri/card0", "/dev/dri/renderD128"),
            "render_access": True,
            "opengl_renderer": "virgl (Mesa Intel(R) Graphics (ARL-S))",
            "vulkan_devices": (),
            "selected_device": "",
            "packages": {},
            "boot_id": "boot-a",
        }
        values.update(changes)
        return GraphicsReport(**values)

    def test_virgl_opengl_passes_without_vulkan(self):
        passed, failures = evaluate_launch_graphics(self.report())

        self.assertTrue(passed)
        self.assertEqual(failures, ())

    def test_software_vulkan_does_not_block_virgl_opengl(self):
        passed, failures = evaluate_launch_graphics(
            self.report(
                vulkan_devices=(
                    {
                        "name": "llvmpipe (LLVM 20.1.2)",
                        "driver": "lavapipe",
                        "type": "PHYSICAL_DEVICE_TYPE_CPU",
                    },
                ),
                selected_device="llvmpipe (LLVM 20.1.2)",
            )
        )

        self.assertTrue(passed)
        self.assertEqual(failures, ())

    def test_missing_packages_do_not_block_game_launch(self):
        passed, failures = evaluate_launch_graphics(self.report(packages={}))

        self.assertTrue(passed)
        self.assertEqual(failures, ())

    def test_wrong_session_resolution_and_access_fail(self):
        passed, failures = evaluate_launch_graphics(
            self.report(session="wayland", resolution=(1024, 768), render_access=False)
        )

        self.assertFalse(passed)
        self.assertIn("X11 session is required", failures)
        self.assertIn("active display is below 1280x720", failures)
        self.assertIn("render node is not accessible", failures)

    def test_software_opengl_fails(self):
        passed, failures = evaluate_launch_graphics(
            self.report(opengl_renderer="llvmpipe (LLVM 20.1.2)")
        )

        self.assertFalse(passed)
        self.assertIn("software OpenGL renderer selected", failures)

    def test_initial_vm_profile_requires_virgl(self):
        passed, failures = evaluate_launch_graphics(
            self.report(opengl_renderer="Mesa Intel(R) Graphics (ARL-S)")
        )

        self.assertFalse(passed)
        self.assertIn("VirGL OpenGL renderer is not selected", failures)

    def test_missing_render_node_fails(self):
        passed, failures = evaluate_launch_graphics(
            self.report(drm_nodes=("/dev/dri/card0",))
        )

        self.assertFalse(passed)
        self.assertIn("DRM render node is missing", failures)

    def test_json_labels_vulkan_as_diagnostic_and_has_gate_result(self):
        data = self.report().to_json()

        self.assertTrue(data["gate_passed"])
        self.assertEqual(data["gate_profile"], "proxmox-virgl")
        self.assertEqual(data["vulkan_role"], "diagnostic-only")
        self.assertNotIn("environment", data)
        self.assertNotIn("processes", data)


if __name__ == "__main__":
    unittest.main()
