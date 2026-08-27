# Architecture

The official Beanfun site issues an authenticated NGM launch request after the operator signs in. A narrowly scoped Chromium policy hands that request to a private freedesktop handler. The Python core validates game code `2982`, keeps the private values out of logs, performs an automatic current-boot graphics check when needed, and launches the Windows client as an argument vector without a shell.

The initial graphics path is:

```text
PVE Intel iGPU and i915
  → QEMU virtio-vga-gl and virglrenderer
  → Lubuntu Mesa VirGL OpenGL
  → Wine 11.10 WineD3D
  → Maplestory_Classic.exe
```

Vulkan/Venus remains useful diagnostic information but is not the MapleStory rendering path. Distribution-neutral protocol, privacy, runtime, and audit code is separated from the Lubuntu package/desktop adapter and the read-only Proxmox operator tooling.
