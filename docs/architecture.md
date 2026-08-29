# Architecture

The official Beanfun site issues an authenticated NGM launch request after the operator signs in. A narrowly scoped Chromium policy hands that request to a private freedesktop handler. The Python core validates game code `2982`, keeps the private values out of logs, performs an automatic current-boot graphics check when needed, and launches the Windows client as an argument vector without a shell.

The initial graphics path is:

```text
PVE Intel iGPU and i915
  → QEMU virtio-vga-gl and virglrenderer
  → Lubuntu Mesa VirGL OpenGL
  → hash-verified Wine 11.10 NTDLL patch + WineD3D
  → Maplestory_Classic.exe
```

The runtime builder starts from a locked Wine archive, applies one audited patch to one NTDLL source file at a pinned upstream commit, and accepts only the exact known-good DLL hash. The Windows service path is equally narrow:

```text
grap64.dll
  → Wine Service Control Manager
  → game-shipped NGService.exe
  → game-shipped grap-core64.aes
```

The installer never fabricates GRAP arguments or service entries. It creates a complete Wine prefix, invokes the vendor's own `NGService.exe -install`, and rejects a prefix that lacks `RpcSs`, `PlugPlay`, `NGS`, or the installed broker.

The protocol handler builds a deliberately small environment rather than
forwarding the browser's complete environment. In addition to display, audio,
and D-Bus state, it forwards `XMODIFIERS`, `GTK_IM_MODULE`, and
`QT_IM_MODULE` so Wine's X11 driver can open the active Fcitx XIM service.

For the supported Lubuntu X11 session, the handler also invokes a small
per-game input-profile manager. It leaves Fcitx in the user's selected mode,
transactionally snapshots the user's Openbox file, and enumerates the running
LXQt shortcut daemon through `org.lxqt.global_key_shortcuts`. The profile keeps
`Alt+Tab` and `Alt+Shift+Tab`, disables non-hardware LXQt actions through their
D-Bus action IDs, and preserves XF86 and brightness controls. A `finally`
cleanup restores the exact Openbox bytes and every saved LXQt enabled state;
`msclassic input status` and `msclassic input restore` expose safe inspection
and crash recovery. It never edits the LXQt shortcut file, restarts the LXQt
daemon, or writes system configuration.

Optional authorized debugging has a separate launcher boundary. It accepts
only a readable Windows `.exe`, starts it with the exact pinned Wine binary and
the exact game prefix, and does not forward browser secrets. Native Linux
debugger attachment is deliberately unsupported because Linux `ptrace` stops
interfere with Wine's implementation of Windows thread suspend/context calls.

Vulkan/Venus remains useful diagnostic information but is not the MapleStory rendering path. Distribution-neutral protocol, privacy, runtime, and audit code is separated from the Lubuntu package/desktop adapter and the read-only Proxmox operator tooling. Runtime profile v1 still has one intentional platform constraint: Wine's embedded build path is locked to `/home/ubuntu`; removing it is required before other usernames/distributions can be declared supported.
