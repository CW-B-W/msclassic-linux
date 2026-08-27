# MS Classic Linux

Unofficial community tooling for running MapleStory Classic on Linux. The initial supported environment is **Lubuntu 24.04 in a Proxmox VM using shared VirGL graphics**.

This repository does not contain the game client, Wine archives, credentials, browser profiles, authentication values, or any authentication/anti-cheat bypass. It uses the official Beanfun GamePass website and a locally installed handler to launch the legitimate Windows client through Wine.

## Current status

- Validated Windows runtime: Wine 11.10 staging/TkG WoW64.
- Rendering path: WineD3D → Mesa VirGL OpenGL.
- No GPU passthrough.
- Authenticated client launch and 1366×768 rendering validated on Lubuntu 24.04/PVE.
- Character/map acceptance remains pending when the service is out of maintenance.
- Fedora, Arch Linux, native hardware, Wayland, and NVIDIA are roadmap targets, not supported claims.

See [Architecture](docs/architecture.md) and the [design specification](docs/superpowers/specs/2026-08-27-ms-classic-linux-clean-project-design.md).

## Safety boundary

The project never changes Proxmox itself. Host changes are performed by the operator in Proxmox WebUI. Guest installation has a zero-mutation planning mode and verifies downloaded artifacts cryptographically.
