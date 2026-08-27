from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .commands import CommandError, run_allowlisted
from .paths import AppPaths
from .redaction import assert_export_safe


@dataclass(frozen=True)
class GraphicsReport:
    kernel: str
    session: str
    resolution: tuple[int, int] | None
    drm_nodes: tuple[str, ...]
    render_access: bool
    opengl_renderer: str
    vulkan_devices: tuple[dict[str, str], ...]
    selected_device: str
    packages: dict[str, str]
    boot_id: str

    def to_json(self) -> dict[str, object]:
        passed, failures = evaluate_launch_graphics(self)
        data = asdict(self)
        data["resolution"] = list(self.resolution) if self.resolution else None
        data["gate_profile"] = "proxmox-virgl"
        data["vulkan_role"] = "diagnostic-only"
        data["gate_passed"] = passed
        data["failures"] = list(failures)
        assert_export_safe(data)
        return data


def parse_opengl_renderer(output: str) -> str:
    match = re.search(r"^OpenGL renderer string:\s*(.+)$", output, re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_vulkan_devices(output: str) -> tuple[dict[str, str], ...]:
    devices: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in output.splitlines():
        if re.fullmatch(r"GPU\d+:", line.strip()):
            if current and current.get("name"):
                devices.append(current)
            current = {"name": "", "driver": "", "type": ""}
            continue
        if current is None or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "deviceName":
            current["name"] = value
        elif key == "driverName":
            current["driver"] = value
        elif key == "deviceType":
            current["type"] = value
    if current and current.get("name"):
        devices.append(current)
    return tuple(devices)


def parse_active_resolution(output: str) -> tuple[int, int] | None:
    match = re.search(r"^\s*(\d+)x(\d+)\s+[^\n]*\*", output, re.MULTILINE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def evaluate_launch_graphics(
    report: GraphicsReport,
) -> tuple[bool, tuple[str, ...]]:
    """Evaluate only the graphics path MapleStory actually uses on this profile."""

    failures: list[str] = []
    if report.session.lower() != "x11":
        failures.append("X11 session is required")
    if report.resolution is None or report.resolution[0] < 1280 or report.resolution[1] < 720:
        failures.append("active display is below 1280x720")
    if not any(Path(node).name.startswith("renderD") for node in report.drm_nodes):
        failures.append("DRM render node is missing")
    if not report.render_access:
        failures.append("render node is not accessible")
    opengl = report.opengl_renderer.lower()
    if not opengl:
        failures.append("OpenGL renderer is unavailable")
    elif any(name in opengl for name in ("llvmpipe", "softpipe", "swrast")):
        failures.append("software OpenGL renderer selected")
    elif "virgl" not in opengl:
        failures.append("VirGL OpenGL renderer is not selected")
    return not failures, tuple(failures)


# Compatibility alias for early adopters of the exploratory implementation.
evaluate_graphics = evaluate_launch_graphics


def collect_graphics_report(
    paths: AppPaths,
    *,
    env: Mapping[str, str] | None = None,
) -> GraphicsReport:
    del paths  # Reserved for future adapter-specific report metadata.
    environment = os.environ if env is None else env
    outputs = {
        "kernel": _probe("kernel", ["uname", "-r"]),
        "glx": _probe("opengl", ["glxinfo", "-B"]),
        "vulkan": _probe("vulkan", ["vulkaninfo", "--summary"], timeout=45.0),
        "xrandr": _probe("display", ["xrandr", "--current"]),
        "packages": _probe(
            "packages",
            ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\\n"],
        ),
    }
    drm_nodes = tuple(sorted(str(path) for path in Path("/dev/dri").glob("*")))
    render_nodes = [Path(node) for node in drm_nodes if Path(node).name.startswith("renderD")]
    packages: dict[str, str] = {}
    for line in outputs["packages"].splitlines():
        name, separator, version = line.partition("\t")
        if separator and name in {
            "libvulkan1:i386",
            "mesa-utils",
            "mesa-vulkan-drivers:i386",
            "vulkan-tools",
        }:
            packages[name] = version
    devices = parse_vulkan_devices(outputs["vulkan"])
    try:
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        boot_id = "unavailable"
    return GraphicsReport(
        kernel=outputs["kernel"].strip(),
        session=environment.get("XDG_SESSION_TYPE", ""),
        resolution=parse_active_resolution(outputs["xrandr"]),
        drm_nodes=drm_nodes,
        render_access=bool(render_nodes)
        and all(os.access(node, os.R_OK | os.W_OK) for node in render_nodes),
        opengl_renderer=parse_opengl_renderer(outputs["glx"]),
        vulkan_devices=devices,
        selected_device=devices[0]["name"] if devices else "",
        packages=packages,
        boot_id=boot_id,
    )


def _probe(category: str, argv: list[str], *, timeout: float = 30.0) -> str:
    executable = shutil.which(argv[0])
    if executable is None:
        return ""
    try:
        result = run_allowlisted(
            category,
            [executable, *argv[1:]],
            {Path(executable)},
            timeout=timeout,
        )
    except CommandError:
        return ""
    return result.stdout if result.exit_code == 0 else ""
