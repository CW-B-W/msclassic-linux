# Successful MapleStory Classic Linux launch — 2026-08-27

## Result

MapleStory Classic accepted a live Beanfun GamePass login, started its Windows client on Lubuntu 24.04, rendered at 1366×768, selected a character, and entered a live map. The repaired Wine service prefix started the vendor `NGService.exe`; it spawned `grap-core64.aes`, and the security module no longer forced the client closed. MapleStory, GRAP core, and Unity Crash Handler remained alive together through the observation period.

The character moved with held arrow keys through both Proxmox noVNC and AnyDesk. RustDesk alone reduced held arrow input to ineffective taps on the Linux guest, although the same RustDesk client worked with the Windows reference VM. This isolates that symptom to RustDesk's Linux-host input path, not MapleStory or Wine. A later game-only session remained stable for about four hours. Chinese input, clean post-debugger recovery/relaunch, post-reboot launch, and multi-VM capacity remain pending.

No GPU passthrough, SR-IOV, Windows VM, authentication bypass, anti-cheat bypass, saved credential, or copied browser profile was used.

```text
Intel iGPU owned by PVE/i915
  -> QEMU virtio-vga-gl / virglrenderer
  -> Lubuntu Mesa VirGL OpenGL
  -> patched Wine 11.10 WineD3D/OpenGL
  -> Maplestory_Classic.exe (Unity)
  -> grap64.dll -> NGService.exe -> grap-core64.aes
```

Vulkan was not the successful game path. Venus enumerated, while an independent PPSSPP comparison showed that Vulkan command/fence work could stall even though OpenGL remained healthy.

## Exact observed environment

| Item | Observed value |
| --- | --- |
| PVE | manager 9.2.3, kernel 7.0.6-2-pve |
| QEMU packages | `qemu-server 9.1.16`, `pve-qemu-kvm 11.0.0-4` |
| Host GPU | Intel Arrow Lake-S `8086:7d67`, `i915` |
| Render node | `/dev/dri/renderD128` |
| Host packages | `virgl-server 1.1.0-2`, `mesa-vulkan-drivers 25.0.7-2+deb13u1` |
| VM | 80001 `Brad-Lubuntu-MS`, OVMF, q35, 8 vCPU, 16 GiB |
| Display | VirGL GPU; no passed-through PCI device |
| Additions | `hostmem=2G`, `blob=on`, `venus=on` |
| Guest | Lubuntu 24.04, X11, kernel 7.0.0-30-generic |
| Desktop | 1440×900 over AnyDesk |
| OpenGL | `virgl (Mesa Intel(R) Graphics (ARL))` |
| Game window | 1366×768 |
| Wine | `wine-11.10-staging-tkg-amd64-wow64-msclassic1` |
| Prefix | `~/.local/share/maplestory-classic/prefix-wine1110` |

The generated QEMU fragments were:

```text
-display 'egl-headless,gl=core'
-device 'virtio-vga-gl,id=vga,bus=pcie.0,addr=0x1'
-set 'device.vga.hostmem=2G'
-set 'device.vga.blob=on'
-set 'device.vga.venus=on'
```

All Proxmox changes were performed personally by the operator through WebUI. The project did not change PVE.

## Runtime lock

```text
Wine URL: https://github.com/Kron4ek/Wine-Builds/releases/download/11.10/wine-11.10-staging-tkg-amd64-wow64.tar.xz
Wine size: 97357652 bytes
Wine SHA-256: 5355cff72783e30f96e3e47aef440b0408a7bf550e53a00c8df139186f37ea25
nxdl version: v0.1.2-prerelease3
nxdl SHA-256: 256582f47dec30a3ba1482571dacfc4c387c746b5061a52c5659b8b2eadedf7d

Wine source: https://github.com/Kron4ek/wine-tkg.git
Wine source commit: 4b12965ca7e78b8e45eee5f835c72963b3ce351d
Patch: patches/wine-11.10-ntdll-frame-walk-page-fault-guard.patch
Patch SHA-256: 0a438e21f7d12ea337b9119c7cc2f48f99e2bf6fe38abc00070d9aa46a03ca06
Patched NTDLL SHA-256: 2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d
```

GE-Proton11-3 and GE-Proton11-5 were not the final solution. Both exposed a Wine 11.0 base and aborted when Unity called `UIAutomationCore.DLL.UiaDisconnectAllProviders`. The pinned Wine 11.10 runtime implements the required API. A narrow, source-built NTDLL page-fault guard adapted from the CyderBits compatibility finding prevented the later frame-walk crash. The repository builds it from the exact source commit and rejects any output whose size or hash differs.

Wine embeds the source path in NTDLL. The first reproducible profile therefore pins `/home/ubuntu/.cache/msclassic-build` and supports the current `/home/ubuntu` Lubuntu template only. A path-independent build is roadmap work.

## Browser flow

The successful personal sequence was:

1. Open the official Classic page in Chromium.
2. Choose GamePass—not the Hong Kong login method.
3. Choose Google and the default Google account.
4. Choose the Beanfun account `bradhk`.
5. Launch from the Classic page.
6. Let Chromium dispatch the site's external request to the private handler.

The handler accepts only the expected Classic game code, decodes within strict bounds, passes arguments directly to Wine without a shell, and never records authenticated values. The managed Chromium policy allows only `ngm` and only from `https://maplestoryclassic.beanfun.com`.

## Why earlier attempts appeared inert

1. Chromium did invoke the external handler; the handler/runtime exited before a window appeared.
2. A stale boot-scoped graphics approval initially stopped the old handler. The clean project now performs that check automatically on the first website launch after each boot.
3. Wine 11.0-based Proton builds aborted on a missing UI Automation implementation.
4. Vulkan enumeration was mistaken for proof of a usable Vulkan workload. The working MapleStory path avoided Vulkan and used WineD3D/OpenGL.
5. The first Wine prefix had registry files but almost no standard services. A clean prefix plus the vendor's own `NGService.exe -install` workflow supplied `RpcSs`, `PlugPlay`, the `NGS` service, and its broker.
6. A native Linux Cheat Engine debugger attachment eventually caused Unity's
   garbage collector to report `SuspendThread loop failed`, even without a
   value scan. An isolated 64-thread Windows probe reproduced failed Wine
   suspend/context calls under Linux `ptrace`; the same probe remained healthy
   with Windows Cheat Engine running inside the same Wine server.

## Relationship to the macOS community work

The [Bahamut guide](https://forum.gamer.com.tw/C.php?bsn=7650&snA=1037767), [CitrusGate](https://github.com/dspp779/CitrusGate), and [CyderBits](https://github.com/dspp779/CyderBits) established the key pattern: a Wine compatibility layer, a Classic client outside Git, and an external Nexon/Beanfun launch handoff. CitrusGate also documents nxdl integration and the NexonPlug workflow; CyderBits keeps Wine runtime concerns separate from its application layer.

This Linux project reimplements only the needed concepts for freedesktop MIME handlers, Chromium policy, a distribution adapter, and shared VirGL. It does not copy the macOS application, Apple graphics backends, credentials, or private launch values. Backend advice is platform-specific: the forum's macOS configuration favors DXVK/D3DMetal and warns about WineD3D there, while this particular Linux VirGL VM was proven with WineD3D/OpenGL and had unreliable Vulkan behavior.

## Remaining acceptance

| Check | Status |
| --- | --- |
| No GPU passthrough | pass |
| Shared host iGPU through VirGL | pass |
| GamePass/Google authentication | pass |
| Official website protocol handoff | pass |
| Unity window at 1366×768 | pass |
| Reached game service/maintenance flow | pass |
| Character selection and map entry | pass |
| Offline NGS service registration and installed broker | pass |
| Live `NGService.exe` → `grap-core64.aes` lifecycle | pass |
| Local held-arrow character movement | pass |
| Proxmox noVNC arrow movement | pass |
| AnyDesk arrow movement with normal operator settings | pass |
| RustDesk arrow movement on Linux guest | fail; not recommended for gameplay |
| Game-only stability for about four hours | pass |
| Fcitx/XIM environment propagation | pass in isolated Wine probe; in-game confirmation pending |
| Native Linux `ptrace` debugger attachment | fail; incompatible with Wine thread-context handling |
| Same-prefix Windows debugger probe | pass: scan, 10-minute attach, clean detach, zero probe failures |
| Clean post-debugger recovery and relaunch | pending |
| First launch after reboot with automatic doctor | pending final live confirmation |
| Two concurrent VMs | pending after single-VM gameplay |

See [the quick start](quick-start-lubuntu-pve.md) for the guarded reproduction procedure.
