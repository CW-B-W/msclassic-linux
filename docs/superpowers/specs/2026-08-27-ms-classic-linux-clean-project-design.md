# MS Classic Linux Clean Project Design

**Date:** 2026-08-27

**Project directory:** `/home/ubuntu/ms-classic-linux`

**Initial supported target:** Lubuntu 24.04 as a Proxmox VM with shared VirGL graphics

## Purpose

Create a clean personal project for making MapleStory Classic playable on Linux. The architecture is distribution-neutral, while support claims remain evidence-based: Lubuntu 24.04 on Proxmox is the only initially supported environment. Native Lubuntu, other Ubuntu/LXQt combinations, Fedora, Arch Linux, physical machines, and other graphics stacks are roadmap targets until individually tested.

The project extracts the proven implementation from the experimental workspace without carrying temporary probes, obsolete GE-Proton/UMU configuration, browser session data, downloaded runtimes, or game files.

## Goals

- Reproduce the validated Lubuntu 24.04 Proxmox installation on a fresh VM.
- Launch the official Windows client from the official Beanfun GamePass website flow.
- Use shared VirtIO-GPU/VirGL rather than GPU passthrough.
- Use checksum-pinned Wine 11.10 with WineD3D/OpenGL.
- Keep platform-independent launch, validation, audit, and privacy logic separate from distribution-specific installation.
- Make every mutation previewable, explicit, auditable, and safe to repeat.
- Provide a clear path for adding tested distribution and hardware adapters later.

## Non-goals

- Modifying the game executable or bypassing anti-cheat or authentication.
- Storing credentials, cookies, browser profiles, authenticated launch values, or game binaries.
- Automatically changing Proxmox configuration.
- Claiming untested Fedora, Arch, Wayland, NVIDIA, or physical-machine support.
- Providing a general-purpose Wine manager.

## Portability and Expected Effort

The game, authentication handoff, missing Wine API, and working OpenGL translation path have already been identified. Porting therefore focuses on package management, graphics validation, desktop integration, and acceptance testing.

| Target | Expected effort | Main work |
| --- | --- | --- |
| Lubuntu 24.04 on an Intel/AMD physical machine using X11 | Low to medium | Add a native-GPU profile, remove the VirtIO/Venus requirement from the doctor, validate Mesa OpenGL and WineD3D, and run the acceptance checklist. Native hardware may be simpler than VirGL. |
| Lubuntu on a physical NVIDIA machine | Medium to high | Validate proprietary or Nouveau drivers, 32-bit userspace, OpenGL behavior, and remote-desktop/display integration. |
| Fedora or Arch VM on the same Proxmox VirGL host | Medium | Add a package-manager adapter, multilib packages, locale handling, Chromium policy location, desktop-handler installation, and Fedora SELinux handling where applicable. The Proxmox and Wine logic should remain unchanged. |
| Fedora or Arch on Intel/AMD physical hardware using X11 | Medium | Combine the distribution adapter with a native-GPU doctor profile and perform a full login/gameplay acceptance run. |
| Other distribution on Wayland or NVIDIA physical hardware | Medium to high | Add display-session and driver variants, validate XWayland or native behavior, input/focus, 32-bit libraries, and rendering stability. |

These are relative effort levels, not support promises. Each target becomes supported only after its adapter tests and live acceptance run pass.

## Architecture

```text
Official Beanfun website in Chromium
  -> authenticated NGM launch request
  -> Linux desktop protocol handler
  -> distribution-neutral parser and privacy boundary
  -> checksum-validated Wine 11.10 runtime
  -> dedicated Wine prefix
  -> WineD3D translates Direct3D to OpenGL
  -> platform graphics adapter
       current: Mesa VirGL -> QEMU virtio-vga-gl -> host Intel iGPU
  -> Maplestory_Classic.exe
```

### Distribution-neutral core

The Python package owns:

- Strict NGM and NexonPlug parsing for game code `2982`.
- Argument-vector launch without a shell.
- Authenticated-value redaction and export guards.
- Artifact manifest parsing and cryptographic verification.
- Wine runtime and dedicated-prefix launch behavior.
- Current-boot graphics approval handling.
- Update, stop, audit, and reproduction commands.
- Platform capability interfaces and normalized doctor reports.

The core does not invoke `apt`, `dnf`, or `pacman` directly. It requests actions from the selected adapter.

### Platform adapters

An adapter declares:

- How to identify the operating system and version.
- Required packages and architecture/multilib setup.
- Supported display sessions and graphics profiles.
- Chromium managed-policy destination.
- Desktop MIME database commands.
- Read-only preflight checks.
- Explicit install actions and rollback notes.

The initial adapter is `lubuntu-24.04`. Future adapters are added only when implemented and tested; the repository will use a roadmap document rather than empty Fedora/Arch code stubs.

### Proxmox integration

Proxmox support consists of:

- A read-only host preflight script.
- An operator-facing WebUI procedure.
- A validated VM profile containing VirGL and the three additive QEMU properties.
- Rollback instructions.

The project never runs `qm set`, installs PVE packages, starts/stops a VM, or changes a PVE configuration. The operator performs visible PVE mutations personally.

## Repository Layout

```text
ms-classic-linux/
├── README.md
├── pyproject.toml
├── versions.lock
├── src/msclassic/
│   ├── cli.py
│   ├── protocol.py
│   ├── runner.py
│   ├── artifacts.py
│   ├── doctor.py
│   ├── audit.py
│   ├── redaction.py
│   └── platforms/
│       ├── base.py
│       └── lubuntu_2404.py
├── platforms/
│   ├── lubuntu-24.04/
│   │   ├── install.sh
│   │   ├── chromium-policy.json
│   │   └── maplestory-classic.reg
│   └── proxmox/
│       ├── readonly-preflight.sh
│       └── pve-virgl.toml
├── desktop/
├── docs/
│   ├── quick-start-lubuntu-pve.md
│   ├── architecture.md
│   ├── troubleshooting.md
│   ├── adding-a-platform.md
│   └── roadmap.md
├── tests/
├── scripts/
│   ├── test.sh
│   └── secret-scan.sh
└── reports/reference/
```

## Command Interface

The installed CLI provides:

```text
msclassic doctor
msclassic plan --platform lubuntu-24.04 --source PATH
msclassic install --platform lubuntu-24.04 --source PATH
msclassic handle-url URI
msclassic update [--apply]
msclassic stop --yes
msclassic reproduce
msclassic uninstall
```

`plan` is always non-mutating. `install` repeats preflight checks, prints the selected adapter and locked artifacts, then performs explicit guest mutations. Package and system-policy changes may use `sudo`; no PVE command does.

## Installation Flow

1. The operator completes and audits the documented Proxmox setup.
2. `doctor` identifies the Lubuntu adapter, X11, current resolution, VirGL OpenGL, expected DRM access, and required guest packages.
3. `plan` validates the read-only game source, calculates disk requirements, and lists package, download, client-copy, prefix, policy, and handler actions without mutation.
4. `install` repeats the gate and installs the adapter's packages.
5. The installer downloads Wine and nxdl over HTTPS and validates the locked size and digest before extraction or installation.
6. It copies the game client into the user's game directory; it never alters the mounted source.
7. It creates a dedicated Wine prefix, applies narrow registry settings, installs the scoped Chromium policy and private desktop handler, and installs user commands.
8. On the first website launch after a reboot, the handler detects the missing or stale boot approval, runs the launch graphics check automatically, writes the current-boot stamp when it passes, and continues without requiring a terminal command. Manual `doctor` remains available for troubleshooting.
9. The operator logs in personally using GamePass, Google, the default account, and the selected Beanfun profile.

## Runtime and Browser Behavior

- Wine runtime: `wine-11.10-staging-tkg-amd64-wow64`, pinned by size and SHA-256.
- Graphics translation: WineD3D to OpenGL. DXVK/Vulkan is not used by the game.
- Prefix: dedicated to MapleStory Classic and stopped only by its pinned `wineserver`.
- Browser policy: allows the `ngm` protocol only from the official Classic origin.
- Handler: accepts only supported schemes, one game code, bounded input, and valid field structure.
- First-launch gate: automatically validates the current boot inside the handler; a failure produces a fixed desktop notification without exposing authenticated arguments.
- Private arguments are never written to logs, reports, shell history, or status receipts.

## Error Handling and Rollback

- Fail closed before mutation when the graphics gate, platform detection, disk requirement, source validation, artifact checksum, runtime stamp, or current-boot approval fails.
- Quarantine invalid cached downloads and conflicting runtime directories rather than overwriting them.
- Back up an incompatible existing client directory before importing the source.
- Bound Wine prefix initialization; accept a timeout only when required prefix files exist, then stop only that prefix's server.
- Record launch status using fixed stages and exit codes without authenticated values.
- Retain the client and prefix when uninstalling desktop integration.
- Document PVE rollback separately; the software never performs it.

## Testing

The initial project must retain or add tests for:

- NGM/NexonPlug parsing, malformed inputs, size bounds, and shell-metacharacter isolation.
- Redaction and secret-export rejection.
- Minimal Wine environment and exact argument vector.
- Locked Wine runtime stamp and executable validation.
- Automatic current-boot graphics approval, stamp reuse within one boot, and fail-closed notification behavior.
- Adapter detection and exact Lubuntu package/action plan.
- Dry-run zero-mutation behavior.
- Safe archive extraction and checksum quarantine.
- Fresh-prefix timeout verification and dedicated-server cleanup.
- Chromium policy scope and desktop handler registration/rollback.
- Read-only Proxmox script behavior and absence of mutation commands.
- Secret scan, complete unit/integration suite, and a dry-run against the mounted client.

Live acceptance remains separate from automated tests: website authentication, splash, service login, character selection, map entry, 15-minute gameplay, normal exit, and second launch.

## Migration from the Experimental Workspace

Copy only reviewed, relevant source, tests, policies, profiles, lock data, and documentation. Rename the guest-specific installer into the Lubuntu adapter. Replace experiment-oriented names and comments with product-facing language. Preserve the dated successful-launch report as provenance, but do not copy temporary CDP scripts, screenshots, downloaded archives, Wine prefixes, game files, browser state, stale GE-Proton/UMU artifacts, or unreviewed candidate data.

Initialize `/home/ubuntu/ms-classic-linux` as a new Git repository with its own history. The first implementation milestone is complete when the clean repository passes all tests and its dry-run reproduces the exact Wine 11.10/nxdl plan on the current VM without mutation.

## Acceptance Criteria

- A fresh same-environment VM can follow the quick start without consulting the experimental workspace.
- The installer selects only the Lubuntu 24.04 adapter and refuses unsupported platforms clearly.
- The generated plan uses only the locked Wine 11.10 and nxdl artifacts.
- No Proxmox mutation exists in executable project code.
- No secret-bearing or game/runtime binary enters Git.
- All automated tests and secret scans pass.
- The installed website handler automatically performs current-boot approval when needed and launches without a manual terminal step.
- Unsupported environments are described as roadmap targets, not as working configurations.
