# Lubuntu 24.04 on Proxmox: reproducible setup

This is the initial supported deployment: Lubuntu 24.04 with an X11 session, running as a Proxmox VE 9.1 or 9.2 VM with shared VirGL graphics. It does not pass the Intel GPU through to any VM. The validated result launched MapleStory Classic through the official Beanfun website and reached the game service while it was under maintenance.

The project never changes Proxmox. Every host or VM configuration change below is performed personally by the operator in Proxmox WebUI. The repository's Proxmox helper has only `check` and `webui-plan` modes and cannot apply or roll back a configuration.

## What the stack does

```text
official Beanfun page in Chromium
  -> ngm:// or NexonPlug:// desktop handler
  -> bounded parser; authenticated values remain private
  -> automatic current-boot VirGL/OpenGL check
  -> Wine 11.10 staging/TkG
  -> WineD3D translates Direct3D to OpenGL
  -> Mesa VirGL -> QEMU VirtIO-GPU -> host Intel i915
```

Vulkan/Venus is retained as diagnostic information, but MapleStory does not use DXVK or Vulkan in this profile. No Windows VM, GPU passthrough, authentication bypass, or anti-cheat bypass is involved.

## Validated values

| Layer | Value |
| --- | --- |
| PVE | 9.2.3 observed; 9.1 and 9.2 accepted by the preflight |
| Host GPU | Intel Arrow Lake-S, `i915`, `/dev/dri/renderD128` |
| Host packages | `virgl-server`, `mesa-vulkan-drivers` |
| VM firmware/machine | OVMF, q35 |
| VM display | VirGL GPU (`virtio-gl`) |
| VM additions | `hostmem=2G`, `blob=on`, `venus=on` on `device.vga` |
| Validated VM sizing | 8 vCPU, 16 GiB RAM |
| Guest | Lubuntu 24.04, X11, 1440×900 desktop |
| Game window | 1366×768 |
| Runtime | `wine-11.10-staging-tkg-amd64-wow64` |
| Game renderer | WineD3D/OpenGL, OpenGL renderer containing `virgl` |

The CPU and memory values are the proven starting point, not measured minimums. Reduce them only as a separate capacity trial.

## 1. Prepare the Proxmox node once

In Proxmox WebUI, select the node and open **Shell**. Review and personally run:

```bash
apt update
apt install -y virgl-server mesa-vulkan-drivers
```

This is one node-wide dependency installation, not a per-VM installation. Do not upgrade unrelated packages as part of this procedure.

Still in the WebUI shell, use this read-only inspection block:

```bash
pveversion
lspci -nnk | grep -A3 -Ei 'VGA|3D|Display'
ls -l /dev/dri/renderD128
dpkg-query -W -f='${binary:Package}\t${db:Status-Abbrev}\t${Version}\n' \
  virgl-server mesa-vulkan-drivers
test -x /usr/libexec/virgl_render_server
/usr/bin/kvm -device virtio-vga-gl,help 2>&1 | grep -E 'hostmem|blob|venus'
```

Stop if the render node is missing, Intel is not bound to `i915`, either package is not installed, the render server is not executable, or QEMU does not expose all three properties.

If this repository is deliberately available on the PVE node, the equivalent guarded check for a stopped VM is:

```bash
bash platforms/proxmox/readonly-preflight.sh check VMID
bash platforms/proxmox/readonly-preflight.sh webui-plan VMID
```

The second command prints a change sheet; it does not execute the displayed commands.

## 2. Prepare one VM in WebUI

Start with one VM only.

1. Select the VM → **Summary** → **Shutdown** and wait until it is stopped.
2. Select **Backup** → **Backup now**. Retain a successful ZSTD backup as the rollback point.
3. Under **Hardware**, confirm OVMF firmware and q35 machine type.
4. Under **Hardware → Display → Edit**, select **VirGL GPU**. Do not add a PCI device.
5. Under the PVE node → **Shell**, inspect the stopped VM, replacing `VMID`:

   ```bash
   qm status VMID
   qm config VMID | grep -E '^(name|vga|args):'
   ```

6. Stop if an `args:` line already exists; a manual merge review is required.
7. The stock PVE Hardware form does not expose the three validated QEMU device properties. In the visible WebUI node Shell, review the VMID and personally run:

   ```bash
   qm set VMID --args '-set device.vga.hostmem=2G -set device.vga.blob=on -set device.vga.venus=on'
   ```

8. Audit the result before starting the VM:

   ```bash
   qm config VMID | grep -E '^(vga|args):'
   qm showcmd VMID --pretty | grep -E -- \
     'virtio-vga-gl|egl-headless|hostmem|blob|venus|-set'
   ```

Expected essentials:

```text
-display 'egl-headless,gl=core'
-device 'virtio-vga-gl,id=vga,...'
-set 'device.vga.hostmem=2G'
-set 'device.vga.blob=on'
-set 'device.vga.venus=on'
```

There must be one VirtIO GL display and no passed-through PCI GPU. Start the VM from WebUI and reconnect with AnyDesk.

## 3. Check guest storage and session

The conservative plan for the observed 2.77 GiB client is about 5.05 GiB of free space, including runtime/download and rollback headroom:

```bash
df -h /
echo "$XDG_SESSION_TYPE"
```

Use an X11 session. If Proxmox shows a larger virtual disk but `/` remains the old size, the guest partition/filesystem has not been expanded yet; fix that separately before a fresh installation. The installer refuses insufficient space rather than partially copying the client.

## 4. Clone and preview

```bash
git clone git@github.com:CW-B-W/msclassic-linux.git
cd msclassic-linux
bash scripts/test.sh
bash platforms/lubuntu-24.04/install.sh \
  --dry-run \
  --source /media/ubuntu/MapleStoryClassic
```

Dry-run performs no sudo, package, network, or filesystem mutation. It validates the source tree, reports required space, and lists only the locked Wine 11.10 and nxdl artifacts.

The source must contain the legitimate Windows client, including `Maplestory_Classic.exe`, `UnityPlayer.dll`, `GameAssembly.dll`, and the expected game plug-in tree. Game files are never committed to this repository.

## 5. Install in the guest

Review the dry-run, then run:

```bash
bash platforms/lubuntu-24.04/install.sh \
  --source /media/ubuntu/MapleStoryClassic
```

The two stages are:

1. Lubuntu bootstrap: enable i386, install the adapter's Mesa diagnostics and utilities, generate `zh_TW.UTF-8`, and install the Chromium policy scoped to the official site.
2. Application install: require working X11/VirGL, verify exact artifact hashes, copy or verify the writable client, initialize a dedicated Wine prefix, import narrow input/focus registry settings, install `~/.local/bin/msclassic`, and register the three observed external-protocol MIME spellings with rollback state.

Persistent locations follow XDG conventions:

```text
~/Games/MapleStoryClassic
~/.local/share/maplestory-classic/prefix-wine1110
~/.local/share/maplestory-classic/tools/
~/.cache/maplestory-classic/downloads/
~/.local/state/maplestory-classic/
```

## 6. Verify the guest

```bash
msclassic doctor --json
xdg-mime query default x-scheme-handler/ngm
xdg-mime query default x-scheme-handler/nexonplug
xdg-mime query default x-scheme-handler/NexonPlug
```

Expected: `gate_passed` is true, OpenGL contains `virgl`, and each handler is `msclassic-ngm.desktop`.

`doctor` is a troubleshooting command, not a reboot ritual. After a reboot the first website launch notices that the approval is missing or stale, runs the quick VirGL check automatically, writes a private mode-0600 current-boot stamp, and continues. Later launches in the same boot reuse that stamp.

## 7. Launch through the official website

Open Chromium inside the guest and visit:

<https://maplestoryclassic.beanfun.com/Main?af_click_id=>

The validated personal login sequence is:

1. Choose **GamePass**—not the Hong Kong login method.
2. Choose **Google**.
3. Choose the operator's default Google account.
4. On the Beanfun account step, choose `bradhk`.
5. Return to the Classic page and press its game launch control.
6. If Chromium asks to open an external application, confirm only when the origin is the official site and the protocol is `ngm`.

Normally nothing else needs to be opened. Chromium dispatches the authenticated URL to `msclassic`, which validates game code `2982`, keeps all arguments out of logs, checks graphics if this is the first launch after boot, and starts the pinned Wine runtime.

If the website displays scheduled maintenance before generating a launch request, no handler or game window is expected. Do not redo Proxmox or Wine setup for a server-side maintenance notice.

## 8. Acceptance and scale-out

After maintenance, validate one VM before cloning the setup:

1. Reach character selection and enter a map.
2. Play for 15 minutes at 1280×720 or above.
3. Check audio, keyboard, mouse, focus, frame pacing, and AnyDesk responsiveness.
4. Exit normally and launch again from the website.
5. Reboot the guest and verify one website launch succeeds without manually running doctor.

Then add VM 2, followed by VM 3 and VM 4 only after each concurrency step is stable. Give every clone a unique VMID, name, MAC address, machine UUID, and clean browser profile. Never clone a signed-in Chromium profile, cookies, authentication values, or an active Wine prefix session.

Shared VirGL avoids passthrough scarcity, but host CPU, RAM, iGPU time, and remote-desktop encoding remain finite. Watch Node and VM Summary panels and stop increasing concurrency if frame pacing, memory pressure, crashes, or remote access deteriorate.

## Rollback

For a host-display failure, stop the VM in WebUI and restore the retained backup. A configuration-only rollback, personally executed in WebUI node Shell after reviewing the VMID, is:

```bash
qm set VMID --delete args
```

This removes only the additive custom arguments; it does not guess or overwrite the prior Display selection.

Guest uninstall retains the large client and prefix:

```bash
msclassic uninstall
```

Updates are never automatic:

```bash
msclassic update
msclassic update --apply
```

Use `msclassic stop --yes` only when normal game exit leaves the dedicated prefix running. It invokes that prefix's pinned `wineserver`; it never uses a global `pkill`.
