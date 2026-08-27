# Troubleshooting

Diagnose the first failing layer. Do not change several variables at once, and never paste an authenticated `ngm://` or `NexonPlug://` URL into an issue or terminal log.

## 1. Website shows maintenance

This is server-side. The page may stop before creating an external-protocol request, so neither the handler nor Wine should run. Wait for service to return; do not repeat Proxmox setup.

## 2. Clicking the launch button appears to do nothing

Check handler registration without using a real launch URL:

```bash
xdg-mime query default x-scheme-handler/ngm
xdg-mime query default x-scheme-handler/nexonplug
xdg-mime query default x-scheme-handler/NexonPlug
```

All should report `msclassic-ngm.desktop`. Confirm Chromium policy at `chrome://policy`; the only automatic external-protocol allowance should be `ngm` from `https://maplestoryclassic.beanfun.com`.

Run `msclassic doctor --json`. A normal launch runs the same check automatically when its current-boot stamp is absent; manual doctor is only a way to see details.

The handler emits a fixed desktop notification on failure. It intentionally does not include the URL or private parameters.

## 3. Doctor reports software OpenGL

`llvmpipe`, `softpipe`, or `swrast` means CPU rendering. Check:

```bash
echo "$XDG_SESSION_TYPE"
glxinfo -B
ls -l /dev/dri
xrandr --current
```

The initial profile requires X11, at least 1280×720, accessible `renderD*`, and an OpenGL renderer containing `virgl`. Recheck **Hardware → Display → VirGL GPU** in Proxmox WebUI and cold-start the VM after host/package changes.

## 4. Vulkan is lavapipe or PPSSPP Vulkan stalls

Vulkan is not the MapleStory rendering gate. The successful game path is WineD3D → OpenGL → VirGL. `vulkaninfo` is collected for diagnostics, and CPU fallback devices may appear after the Intel-backed Venus device. A PPSSPP Vulkan failure does not imply that MapleStory's OpenGL path must fail.

Do not install DXVK merely to make the doctor pass; DXVK is not used by this profile.

## 5. Wine exits before a window appears

Confirm the locked runtime and client exist:

```bash
cat ~/.local/share/maplestory-classic/tools/wine-11.10-staging-tkg-amd64-wow64/.msclassic-artifact.json
test -x ~/.local/share/maplestory-classic/tools/wine-11.10-staging-tkg-amd64-wow64/bin/wine
test -r ~/Games/MapleStoryClassic/Maplestory_Classic.exe
test -w ~/Games/MapleStoryClassic/Maplestory_Classic.exe
cat ~/.local/state/maplestory-classic/last-launch-status.json
```

GE-Proton11-3 and GE-Proton11-5 were rejected during the investigation because their Wine 11.0 base aborted when Unity called `UIAutomationCore.DLL.UiaDisconnectAllProviders`. The locked Wine 11.10 build implements the required API and launched successfully. Do not silently substitute another runtime.

The launch status contains only a fixed stage and integer exit code. Authenticated arguments and the full URI are intentionally absent.

## 6. Server selection closes with a security-module message

If the client reaches server selection and shows `安全模組運作中` / `客戶端強制關閉(0)`, first check whether the normal GRAP process tree exists:

```bash
ps -eo pid,ppid,comm,args | grep -E \
  'Maplestory_Classic|UnityCrashHandler64|NGService|grap-core64' | grep -v grep
grep -F '[System\\ControlSet001\\Services\\RpcSs]' \
  ~/.local/share/maplestory-classic/prefix-wine1110/system.reg
grep -F '[System\\ControlSet001\\Services\\PlugPlay]' \
  ~/.local/share/maplestory-classic/prefix-wine1110/system.reg
grep -F '[System\\ControlSet001\\Services\\NGS]' \
  ~/.local/share/maplestory-classic/prefix-wine1110/system.reg
test -f ~/.local/share/maplestory-classic/prefix-wine1110/drive_c/ProgramData/Nexon/NGS/NGService.exe
```

`grap-core64.aes` is a normal x86-64 Windows PE executable despite its suffix. Do not `chmod +x` it, launch it with guessed arguments, create a fake service entry, or disable the security module. The game-shipped `grap64.dll` expects the Wine service manager to start `NGService.exe`, which verifies and launches GRAP with per-session arguments.

Rerun the guest installer to complete the Wine service baseline and invoke the vendor's `NGService.exe -install` workflow. The installer suppresses optional Wine Mono/Gecko prompts during prefix setup and refuses a partial prefix instead of accepting registry files alone.

See [the GRAP / NGS-X investigation](2026-08-27-grap-ngs-investigation.md) for the evidence and CyderBits comparison.

## 7. Another launch or update is active

The game and nxdl share a nonblocking mode-0600 lock. Exit the game normally. If the dedicated prefix is genuinely stuck:

```bash
msclassic stop --yes
```

This does not stop unrelated Wine applications.

## 8. Disk space is insufficient

Preview the exact requirement:

```bash
bash platforms/lubuntu-24.04/install.sh --dry-run \
  --source /media/ubuntu/MapleStoryClassic
df -h /
lsblk
```

Increasing the virtual disk in Proxmox does not automatically enlarge the guest partition and filesystem. If `lsblk` shows a larger disk but `df` shows the old root size, finish the guest-side partition/filesystem expansion using the filesystem-appropriate tool and a backup. This is separate from VirGL and Wine.

## 9. AnyDesk does not return after a display change

Use Proxmox WebUI console first. If the guest is unavailable, stop it in WebUI and restore the backup made before the display trial. Do not add GPU passthrough as a troubleshooting shortcut.

## 10. Safe evidence for a report

Acceptable evidence includes PVE/QEMU versions, package versions, `glxinfo -B`, sanitized doctor JSON, display resolution, fixed launch status, and observations such as “window appeared” or “audio stuttered.”

Never include credentials, OTPs, cookies, browser profiles, complete authenticated URLs, raw handler argv, or screenshots showing those values. Run `bash scripts/secret-scan.sh PATH` before exporting a candidate report.
