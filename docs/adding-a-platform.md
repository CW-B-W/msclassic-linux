# Adding another Linux platform

The Python core is distribution-neutral; only Lubuntu 24.04 on a Proxmox VirGL VM is currently accepted. Unsupported systems fail closed instead of guessing package names or graphics requirements.

## Adapter responsibilities

A distribution adapter declares:

- an exact platform identifier and supported OS release;
- packages for OpenGL/Vulkan diagnostics, multilib, locale, download/archive tools, desktop MIME integration, notifications, and client import;
- the Chromium managed-policy directory;
- a two-stage installer that preserves dry-run as zero-mutation.

Protocol parsing, authentication privacy, artifact verification, Wine command isolation, locks, updates, and audit records stay in the shared Python package.

Runtime reproducibility is a separate prerequisite: the current Wine builders
require `/home/ubuntu/.cache/msclassic-build` and verify exact output hashes.
A new distribution or home path needs a validated build and matching runtime
manifest, not just different package names. The contextual-input patch also
needs live Chinese/chat/gameplay acceptance on the target desktop.

## Graphics profiles are separate from distribution adapters

The current `proxmox-virgl` gate requires X11, at least 1280×720, a writable render node, and OpenGL containing `virgl`. It deliberately ignores Vulkan success for the game launch.

A physical Intel/AMD machine should receive a new native-Mesa profile rather than weakening the VirGL check. A Fedora/Arch VM can reuse the VirGL profile while supplying a new package/SELinux/Chromium adapter.

## Evidence required for support

1. Exact `/etc/os-release` values and package versions.
2. Package-manager commands for 64-bit and 32-bit userspace.
3. Locale generation and Chromium policy location.
4. X11 session, `glxinfo -B`, DRM permissions, and 1280×720-or-higher output.
5. Installer dry-run proving zero mutation.
6. Synthetic Wine start using the locked runtime.
7. Personal official-site login, game window, character/map entry, 15-minute play, normal exit, relaunch, and post-reboot automatic launch.
8. Redacted trial record with exactly one changed variable.

## Development sequence

1. Add failing adapter and package-plan tests.
2. Implement `src/msclassic/platforms/<adapter>.py`.
3. Add `platforms/<adapter>/install.sh`, policy, and any narrowly scoped registry file.
4. Validate the Wine build and desktop input integration; add a graphics profile
   only when the hardware path differs.
5. Run `bash scripts/test.sh`, the secret scan, and a real zero-mutation dry-run.
6. Promote support only after the acceptance evidence above.

Do not copy signed-in browser profiles, prefixes with active sessions, machine identifiers, or authenticated parameters between test systems.
