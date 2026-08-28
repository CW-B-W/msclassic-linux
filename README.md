# MS Classic Linux

Unofficial community tooling for running MapleStory Classic on Linux. The initial supported environment is **Lubuntu 24.04 in a Proxmox VM using shared VirGL graphics**.

This repository does not contain the game client, Wine archives, credentials, browser profiles, authentication values, or any authentication/anti-cheat bypass. It uses the official Beanfun GamePass website and a locally installed handler to launch the legitimate Windows client through Wine.

## Current status

- Validated Windows runtime: Wine 11.10 staging/TkG WoW64 plus the audited
  NTDLL frame-walk guard built by this repository.
- Rendering path: WineD3D → Mesa VirGL OpenGL.
- No GPU passthrough.
- Authenticated client launch and 1366×768 rendering validated on Lubuntu 24.04/PVE.
- GamePass login, server/character selection, live map entry, and the vendor
  security chain are validated. `Maplestory_Classic.exe`, `grap-core64.aes`,
  and `UnityCrashHandler64.exe` remained alive together in the map.
- Character movement and held arrow keys are validated through Proxmox noVNC
  and AnyDesk with their normal settings. RustDesk is not recommended for
  gameplay on this Linux guest because its held-arrow delivery was reduced to
  taps; this did not occur on the Windows reference VM.
- An operator-observed game-only session remained stable for about four hours.
- The launcher now preserves the active Fcitx 5 environment for Wine/XIM.
  Chinese composition needs confirmation on the next authenticated launch.
- Fedora, Arch Linux, native hardware, Wayland, and NVIDIA are roadmap targets, not supported claims.

The live result is documented in [Successful launch — 2026-08-27](docs/2026-08-27-successful-launch.md), and the security-service diagnosis and repair are tracked in [GRAP / NGS-X investigation — 2026-08-27](docs/2026-08-27-grap-ngs-investigation.md). Chinese input, clean post-debugger recovery/relaunch, reboot, and multi-VM acceptance remain pending.

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

The current v1 patched-runtime build is deliberately limited to the validated
`ubuntu` account at `/home/ubuntu`. The installer fails early on another home
path. Removing that build-path constraint is a portability milestone, not a
current support claim.

Then use Chromium and the official page: <https://maplestoryclassic.beanfun.com/Main?af_click_id=>. Choose GamePass → Google → your Google account → your Beanfun game account, then launch from the website.

After a reboot, do not run doctor as a ritual. The first website launch automatically checks the current X11/VirGL graphics path and continues if it passes. `msclassic doctor --json` remains available when troubleshooting.

## Commands

```bash
msclassic doctor --json        # manual diagnostics
msclassic plan --source PATH   # zero-mutation plan
msclassic update               # check only
msclassic update --apply       # explicit client update
msclassic stop --yes           # stop only this dedicated Wine prefix
msclassic debugger --windows-ce /path/to/cheatengine-x86_64.exe
msclassic uninstall            # retain client and prefix
```

The debugger command is an optional compatibility aid for software you are
authorized to inspect. Native Linux debuggers that attach to Wine with
`ptrace` are unsupported for this Unity title; see
[Debugger compatibility](docs/debugger-compatibility.md).

## Documentation

- [Architecture](docs/architecture.md)
- [Lubuntu 24.04 / PVE quick start](docs/quick-start-lubuntu-pve.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Debugger compatibility](docs/debugger-compatibility.md)
- [Adding a distribution or hardware profile](docs/adding-a-platform.md)
- [Roadmap and expected porting effort](docs/roadmap.md)
- [Successful launch record](docs/2026-08-27-successful-launch.md)
- [GRAP / NGS-X investigation](docs/2026-08-27-grap-ngs-investigation.md)
- [Design specification](docs/superpowers/specs/2026-08-27-ms-classic-linux-clean-project-design.md)

The original macOS community workflow and compatibility research are credited in the successful-launch record. This repository is a Linux implementation; it does not redistribute CitrusGate, CyderBits, the game, or their runtime payloads.

## Safety boundary

The project never changes Proxmox itself. Host changes are performed by the operator in Proxmox WebUI. `platforms/proxmox/readonly-preflight.sh` has only inspection and plan-printing modes. Guest installation has a zero-mutation planning mode and verifies downloaded artifacts cryptographically.

Authenticated launch data is bounded, passed as an argument vector without a shell, and excluded from status/audit output. Run `bash scripts/secret-scan.sh` before sharing diagnostic artifacts.
