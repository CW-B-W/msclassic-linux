# Roadmap

## Current target

Lubuntu 24.04, user `ubuntu`, X11/Openbox/LXQt, on a Proxmox VirGL VM.
The graphics path remains WineD3D/OpenGL with no GPU passthrough.

## Next acceptance work

1. Reproduce from a fresh second VM using public client download.
2. Run two VMs concurrently, then consider three/four based on measured load.
3. Compare controlled performance captures for fast movement/crowded maps.
4. Validate Sunshine/Moonlight. Use noVNC or AnyDesk in the meantime.
5. Recheck the optional Windows-debugger workflow against the combined release
   runtime; native Linux `ptrace` remains unsupported for the game.

The profiler is available, but no measured crowded-map performance fix is
claimed. VM creation, power operations and host changes stay with the operator
in Proxmox WebUI.

## Future portability

| Environment | Main work |
| --- | --- |
| Lubuntu on Intel/AMD physical hardware | Add native-Mesa graphics validation; test login, input and remote access |
| Ubuntu + LXQt on a Proxmox VM | Validate package/session parity and complete acceptance |
| Fedora or Arch on a VM | Path-independent Wine build, distribution adapter, policy/locale/security integration |
| Fedora or Arch on physical hardware | Distribution work plus native graphics validation |
| Wayland or NVIDIA | Separate input, graphics and remote-desktop validation |

These are plans, not supported-platform claims. The current hard-coded Wine
build path must be removed through a separately validated build before other
home paths/distributions can be advertised as supported.
