# MS Classic Linux

Unofficial community tooling for running MapleStory Classic on Linux. The initial supported environment is **Lubuntu 24.04 in a Proxmox VM using shared VirGL graphics**.

This repository does not contain the game client, Wine archives, credentials, browser profiles, authentication values, or any authentication/anti-cheat bypass. It uses the official Beanfun GamePass website and a locally installed handler to launch the legitimate Windows client through Wine.

## Current status

- Validated Windows runtime: Wine 11.10 staging/TkG WoW64.
- Rendering path: WineD3D → Mesa VirGL OpenGL.
- No GPU passthrough.
- Authenticated client launch and 1366×768 rendering validated on Lubuntu 24.04/PVE.
- Server selection is reachable with the patched Wine candidate. A fresh complete prefix now contains the vendor-installed `NGS` service and broker; live `grap-core64.aes` and map-entry acceptance are pending the next authenticated launch.
- Fedora, Arch Linux, native hardware, Wayland, and NVIDIA are roadmap targets, not supported claims.

The live result is documented in [Successful launch — 2026-08-27](docs/2026-08-27-successful-launch.md), and the security-service diagnosis and repair are tracked in [GRAP / NGS-X investigation — 2026-08-27](docs/2026-08-27-grap-ngs-investigation.md). Character/map and multi-VM acceptance remain pending.

## Quick start

Proxmox configuration is an operator task. Begin with the complete [Lubuntu/PVE quick start](docs/quick-start-lubuntu-pve.md), including its backup and WebUI boundaries.

Inside a prepared Lubuntu guest:

```bash
git clone git@github.com:CW-B-W/msclassic-linux.git
cd msclassic-linux
bash scripts/test.sh
bash platforms/lubuntu-24.04/install.sh \
  --dry-run \
  --source /media/ubuntu/MapleStoryClassic
```

After reviewing the zero-mutation plan:

```bash
bash platforms/lubuntu-24.04/install.sh \
  --source /media/ubuntu/MapleStoryClassic
```

Then use Chromium and the official page: <https://maplestoryclassic.beanfun.com/Main?af_click_id=>. Choose GamePass → Google → your Google account → your Beanfun game account, then launch from the website.

After a reboot, do not run doctor as a ritual. The first website launch automatically checks the current X11/VirGL graphics path and continues if it passes. `msclassic doctor --json` remains available when troubleshooting.

## Commands

```bash
msclassic doctor --json        # manual diagnostics
msclassic plan --source PATH   # zero-mutation plan
msclassic update               # check only
msclassic update --apply       # explicit client update
msclassic stop --yes           # stop only this dedicated Wine prefix
msclassic uninstall            # retain client and prefix
```

## Documentation

- [Architecture](docs/architecture.md)
- [Lubuntu 24.04 / PVE quick start](docs/quick-start-lubuntu-pve.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Adding a distribution or hardware profile](docs/adding-a-platform.md)
- [Roadmap and expected porting effort](docs/roadmap.md)
- [Successful launch record](docs/2026-08-27-successful-launch.md)
- [GRAP / NGS-X investigation](docs/2026-08-27-grap-ngs-investigation.md)
- [Design specification](docs/superpowers/specs/2026-08-27-ms-classic-linux-clean-project-design.md)

The original macOS community workflow and compatibility research are credited in the successful-launch record. This repository is a Linux implementation; it does not redistribute CitrusGate, CyderBits, the game, or their runtime payloads.

## Safety boundary

The project never changes Proxmox itself. Host changes are performed by the operator in Proxmox WebUI. `platforms/proxmox/readonly-preflight.sh` has only inspection and plan-printing modes. Guest installation has a zero-mutation planning mode and verifies downloaded artifacts cryptographically.

Authenticated launch data is bounded, passed as an argument vector without a shell, and excluded from status/audit output. Run `bash scripts/secret-scan.sh` before sharing diagnostic artifacts.
