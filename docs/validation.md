# Validation status

The current personal deployment is Lubuntu 24.04/X11 on Proxmox VirGL with an
Intel iGPU. This page distinguishes observed results from remaining checks.

| Capability | Evidence/status |
| --- | --- |
| Official website launch, server/character selection, live map | Validated on the first VM |
| Game-only session of about four hours | Operator-observed with the base runtime |
| noVNC and AnyDesk movement/held arrows | Validated; RustDesk excluded for now |
| Chinese chat and alphabetic actions with Chinese selected | Operator-confirmed on 2026-08-31 with the exact input DLLs retained in msclassic2 |
| Alt+Space suppression and Alt+Tab access | Operator-confirmed |
| Normal installation includes contextual input | Automated installer/launcher tests; release DLL hashes checked |
| Input state changes with diagnostic logging disabled | Compiled native probe of the patched state-management code |
| Release runtime live acceptance with logging off | Validated on 2026-09-01: automatic website launch, live map, exact msclassic2 modules, normal exit and shortcut restoration |
| First-VM launch after guest reboot without manual doctor | Validated on 2026-09-01; the website launch refreshed and passed the graphics gate for the current boot |
| Fresh second-VM acceptance from public download | Pending |
| Two to four concurrent VMs | Pending capacity measurement |
| Crowded-map/fast-movement stutter | Unresolved; first controlled idle/movement profile points away from memory, swap and storage pressure |
| Sunshine/Moonlight, other distros/hardware | Not yet validated |

## Acceptance on each new VM

1. Complete the [setup guide](quick-start-lubuntu-pve.md), including the
   read-only graphics and handler checks.
2. Launch through Chromium with your own official login.
3. Enter a map and check movement, attack/jump, mouse, audio and focus.
4. Leave Chinese selected: action letters work outside chat, compose Chinese
   inside chat, and work again after chat closes.
5. Confirm Alt+Space does not open the window menu and Alt+Tab still works.
6. Play for at least 15 minutes, close normally, confirm desktop shortcuts
   restore, and relaunch from the website.
7. Reboot the guest through the operator's normal workflow and launch again
   without manually running doctor or diagnostic commands.

Use the same remote client and resolution when comparing performance.
Record only versions, hashes, numeric metrics and non-sensitive observations.
Never publish private launch arguments, account data or raw input logs.

Automated input checks must wait for the chat context to detach before sending
the first gameplay key. A deliberately immediate synthetic `Escape` → `C`
sequence can outrun that context transition; after detach, `C` reaches gameplay
and is not filtered by XIM. This is a test-timing caveat, not a requirement to
run diagnostics or add a delay during normal play.

## First controlled performance profile

On 2026-09-01, the release runtime was profiled on the validated 1366×768 game
window and same quiet map. The comparison used 62 seconds idle and 50 seconds
of alternating held left/right movement:

| Metric | Idle | Movement |
| --- | ---: | ---: |
| Game/Wine CPU, one-core equivalent | 56.0% | 74.5% |
| Average RSS | 1039.1 MiB | 1045.4 MiB |
| Minimum guest memory available | 7874.7 MiB | 7977.7 MiB |
| Swap pages in/out | 0 / 0 | 0 / 0 |
| CPU pressure (`some`) | 1.088% | 1.031% |
| I/O full pressure | 0.108% | 0.010% |

This sample shows higher game/render CPU during movement without memory, swap
or storage pressure. It does not measure frame rate and was not a crowded map,
so it does not identify whether the remaining stutter is in Unity's main
thread, WineD3D, guest VirGL, or the host render path. The next comparison must
repeat the same method on a reproducibly crowded scene.
