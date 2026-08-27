from __future__ import annotations

from .base import PlatformAdapter


LUBUNTU_2404 = PlatformAdapter(
    id="lubuntu-24.04",
    os_id="ubuntu",
    version_id="24.04",
    package_names=(
        "vulkan-tools",
        "mesa-utils",
        "mesa-vulkan-drivers",
        "mesa-vulkan-drivers:i386",
        "libvulkan1",
        "libvulkan1:i386",
        "locales",
        "curl",
        "tar",
        "zstd",
        "python3",
        "xdg-utils",
        "libnotify-bin",
        "rsync",
    ),
    chromium_policy_dir="/etc/chromium/policies/managed",
)
