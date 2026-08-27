# Successful MapleStory Classic Linux launch — 2026-08-27

## Result

MapleStory Classic accepted a live Beanfun GamePass login, started its Windows client on Lubuntu 24.04, rendered at 1366×768, passed the splash screen, and reached the in-game service/maintenance flow. The operator later closed the window normally. Scheduled maintenance prevented character selection and map entry, so this is a validated single-VM launch candidate rather than a completed gameplay or multi-VM capacity result.

No GPU passthrough, SR-IOV, Windows VM, authentication bypass, anti-cheat bypass, saved credential, or copied browser profile was used.

```text
Intel iGPU owned by PVE/i915
  -> QEMU virtio-vga-gl / virglrenderer
  -> Lubuntu Mesa VirGL OpenGL
  -> Wine 11.10 WineD3D/OpenGL
  -> Maplestory_Classic.exe (Unity)
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
| Guest | Lubuntu 24.04, X11, kernel 6.17.0-14-generic |
| Desktop | 1440×900 over AnyDesk |
| OpenGL | `virgl (Mesa Intel(R) Graphics (ARL))` |
| Game window | 1366×768 |
| Wine | `wine-11.10-staging-tkg-amd64-wow64` |
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
```

GE-Proton11-3 and GE-Proton11-5 were not the final solution. Both exposed a Wine 11.0 base and aborted when Unity called `UIAutomationCore.DLL.UiaDisconnectAllProviders`. The pinned Wine 11.10 runtime implements the required API and passed the live launch.

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
| Character selection and map entry | pending after maintenance |
| 15-minute gameplay, exit, relaunch | pending |
| First launch after reboot with automatic doctor | pending final live confirmation |
| Two concurrent VMs | pending after single-VM gameplay |

See [the quick start](quick-start-lubuntu-pve.md) for the guarded reproduction procedure.
