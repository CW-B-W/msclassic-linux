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

Confirm the locked base, audited patched runtime, and client exist:

```bash
cat ~/.local/share/maplestory-classic/tools/wine-11.10-staging-tkg-amd64-wow64/.msclassic-artifact.json
cat ~/.local/share/maplestory-classic/tools/wine-11.10-staging-tkg-amd64-wow64-msclassic1/.msclassic-runtime.json
test -x ~/.local/share/maplestory-classic/tools/wine-11.10-staging-tkg-amd64-wow64-msclassic1/bin/wine
test -r ~/Games/MapleStoryClassic/Maplestory_Classic.exe
test -w ~/Games/MapleStoryClassic/Maplestory_Classic.exe
cat ~/.local/state/maplestory-classic/last-launch-status.json
```

GE-Proton11-3 and GE-Proton11-5 were rejected during the investigation because their Wine 11.0 base aborted when Unity called `UIAutomationCore.DLL.UiaDisconnectAllProviders`. The locked Wine 11.10 build implements the required API. The launcher additionally requires this repository's hash-verified NTDLL frame-walk guard; do not silently substitute another runtime or copy an unrecorded DLL into it.

If a fresh install reports that patched Wine v1 requires `/home/ubuntu`, that is an intentional current-profile boundary. Use the `ubuntu` account in the supported Lubuntu VM template. Other home paths need a future path-independent runtime profile; do not bypass the final hash check.

The launch status contains only a fixed stage and integer exit code. Authenticated arguments and the full URI are intentionally absent.

## 6. Server selection closes with a security-module message

If the client reaches server selection and shows `安全模組運作中` / `客戶端強制關閉(0)`, first check whether the normal GRAP process tree exists:

```bash
ps -eo pid,ppid,comm | grep -E \
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

Rerun the guest installer to complete the Wine service baseline and invoke the vendor's `NGService.exe -install` workflow. The installer suppresses optional Wine Mono/Gecko prompts during prefix setup and refuses a partial prefix instead of accepting registry files alone. The repaired 2026-08-27 profile successfully started `NGService.exe`, kept `grap-core64.aes` alive, and entered a map.

See [the GRAP / NGS-X investigation](2026-08-27-grap-ngs-investigation.md) for the evidence and CyderBits comparison.

## 7. Another launch or update is active

The game and nxdl share a nonblocking mode-0600 lock. Exit the game normally. If the dedicated prefix is genuinely stuck:

```bash
msclassic stop --yes
```

This does not stop unrelated Wine applications.

A Unity fatal-error dialog does not guarantee that the Windows process has
exited. While that failed process remains alive, the handler process correctly
keeps `~/.local/state/maplestory-classic/launch.lock`, so another website click
is rejected instead of spawning a duplicate client. Close the fatal dialog and
game first, or use the dedicated stop command above, then retry the website.

## 8. Disk space is insufficient

Preview the exact requirement:

```bash
bash platforms/lubuntu-24.04/install.sh --dry-run \
  --source /media/ubuntu/MapleStoryClassic
df -h /
lsblk
```

For a first-time public download instead of a mounted source, preview without
network access first, then let the real installer query the manifest and apply
its `total_size + 1 GiB` gate:

```bash
bash platforms/lubuntu-24.04/install.sh --dry-run --download-client
bash platforms/lubuntu-24.04/install.sh --download-client
```

An interrupted download remains at `~/Games/.MapleStoryClassic.download` for
inspection and retry. The installer deliberately refuses to overwrite an
incomplete final client; move it aside only after reviewing it.

Increasing the virtual disk in Proxmox does not automatically enlarge the guest partition and filesystem. If `lsblk` shows a larger disk but `df` shows the old root size, finish the guest-side partition/filesystem expansion using the filesystem-appropriate tool and a backup. This is separate from VirGL and Wine.

## 9. Space/Alt work but arrow keys do not move the character remotely

First distinguish the game from the remote-control layer. Held arrows and
character movement were validated through both Proxmox noVNC and AnyDesk with
the operator's normal settings. No special AnyDesk keyboard mode was required.

RustDesk alone failed this test on the Linux guest: Space could repeat, but
held arrows arrived as taps too short for Unity's movement polling. The same
Mac RustDesk client moved a character normally in a Windows VM. Use noVNC or
AnyDesk for this guest. Sunshine/Moonlight remains untested rather than assumed
working. The behavior resembles the Linux held-key issue tracked upstream in
[RustDesk issue 14360](https://github.com/rustdesk/rustdesk/issues/14360).

This requires no Proxmox, Wine-prefix, IME, or game reinstall. Space and Alt
working does not disprove a remote-input problem: action keys can trigger on
key-down, while movement requires a held state across frames.

## 10. AnyDesk does not return after a display change

Use Proxmox WebUI console first. If the guest is unavailable, stop it in WebUI and restore the backup made before the display trial. Do not add GPU passthrough as a troubleshooting shortcut.

## 11. Chinese input works on the desktop but not in the game

Check the desktop session before opening Chromium:

```bash
pgrep -a fcitx5
printf 'XMODIFIERS=%s\nGTK_IM_MODULE=%s\nQT_IM_MODULE=%s\n' \
  "$XMODIFIERS" "$GTK_IM_MODULE" "$QT_IM_MODULE"
```

Expected values are `@im=fcitx`, `fcitx`, and `fcitx`. The launcher now
preserves all three. An isolated Wine X11 trace changed from a fallback input
context to the five Fcitx-supported XIM styles when these variables were
present. Close and reopen Chromium after correcting the desktop environment,
then start a new game; an already running Windows process cannot acquire the
new environment retroactively.

Do not confuse the OS default browser with the MapleStory protocol handler.
This project registers only `ngm`, `nexonplug`, and `NexonPlug`; it never sets
the default HTTP/HTTPS browser.

## 12. Chinese chat works, but action keys or desktop shortcuts interrupt play

The launcher does not change the selected Fcitx mode. Left Shift remains the
desktop Chinese/English selector, but requiring the player to switch back to
English before alphabetic action keys such as `C` is explicitly not the target
experience. Contextual Wine/X11 routing is under diagnostic development; until
that diagnostic proves a game-owned chat signal, the project does not claim
that Chinese can remain selected during gameplay.

On the development branch, `msclassic input diagnose --persistent` keeps the
experimental candidate selected across website relaunches until
`msclassic input diagnostic-stop`. Without `--persistent`, selection lasts
only one launch: a replacement game may use the original runtime. Status
`enabled` means selected for future launches, not patched into an existing
game. Restart the game to switch builds. These runs record only
category/timestamp events. Exercise
Chinese-selected gameplay, open chat, harmless dummy composition, and closed
chat in that order. The result is accepted only if IME-open state or
composition-rectangle lifetime matches the user-confirmed chat boundaries
exactly; Enter/Escape, screen, timing, and game-memory heuristics are rejected.

Game input mode leaves `Alt+Tab` and `Alt+Shift+Tab` available. It temporarily
disables other Openbox/LXQt desktop bindings, including the observed
`Alt+Space` client-menu binding, only while the official Wine launch is
running. It restores the exact prior per-user shortcut files on game exit.
Openbox restoration is byte-for-byte. LXQt is not rewritten or restarted: the
launcher snapshots action states from the running D-Bus daemon, disables only
non-hardware actions, and restores every saved enabled/disabled state.

Check its state without exposing a website launch URL:

```bash
msclassic input status
```

If a guest crash, forced Wine shutdown, or interrupted remote session left the
temporary desktop profile behind, run this from a separate terminal, SSH
session, or Proxmox console:

```bash
msclassic input restore
```

It is safe to run repeatedly. Do not edit `/etc/xdg/openbox/rc.xml` or disable
LXQt shortcuts globally. The profile intentionally applies only to the
supported Lubuntu X11/Openbox/LXQt session. It cannot control shortcuts that a
remote client consumes before they reach the guest, nor mandatory OS security
controls.

Fcitx background: [input-method environment variables](https://fcitx-im.org/wiki/Input_method_related_environment_variables)
and [Fcitx 5 setup](https://fcitx-im.org/wiki/Setup_Fcitx_5).

## 13. Cheat Engine attachment ends in `SuspendThread loop failed`

Do not use the native Linux Cheat Engine debugger for this Wine/Unity process.
The error reproduced even when no value scan was performed. Linux `ptrace`
controls every Wine thread, while Wine implements Windows suspend/context
operations through its own signal and wineserver protocol. The two control
planes conflict; Unity's Boehm garbage collector eventually cannot suspend a
thread and intentionally terminates the process.

This was not an out-of-memory event: the observed VM retained several GiB of
available RAM and recorded no OOM or pressure stall. GRAP also remained alive,
so the evidence does not attribute the crash to the security module.

For software you are authorized to inspect, follow
[Debugger compatibility](debugger-compatibility.md) and run a Windows debugger
inside the exact MapleStory Wine prefix. Do not use debugging to disable,
patch, conceal from, or bypass GRAP/NGS-X.

The 2026-08-28 supervised acceptance used Windows CE debugger interface 1. It
passed a 10-minute idle attachment, one content-neutral read-only scan, a
five-minute post-scan observation, clean detach, and continued gameplay. This
does not validate breakpoints, watchpoints, or memory modification.

## 13. Safe evidence for a report

Acceptable evidence includes PVE/QEMU versions, package versions, `glxinfo -B`, sanitized doctor JSON, display resolution, fixed launch status, and observations such as “window appeared” or “audio stuttered.”

Never include credentials, OTPs, cookies, browser profiles, complete authenticated URLs, raw handler argv, or screenshots showing those values. Run `bash scripts/secret-scan.sh PATH` before exporting a candidate report.
