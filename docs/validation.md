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
| Crowded-map/fast-movement stutter | Unresolved; optional numeric profiler available |
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
