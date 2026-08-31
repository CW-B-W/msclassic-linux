# Architecture

## Launch path

```text
Official Beanfun website in Chromium
  → ngm / NexonPlug desktop handler
  → bounded authenticated-argument parser
  → automatic current-boot X11/VirGL check
  → Wine 11.10 msclassic2
  → MapleStory Classic + vendor security services

Direct3D → WineD3D → OpenGL → Mesa VirGL → shared host GPU
```

The handler accepts game code `2982`, uses an argument vector without a shell,
and keeps authenticated data out of status output. A small allowlisted
environment carries display, audio, D-Bus and Fcitx settings. The desktop
registration covers game protocols only, never HTTP/HTTPS defaults.

## Runtime construction

The installer verifies the locked Wine archive in `versions.lock`, then builds:

1. `msclassic1`: the audited NTDLL frame-walk page-fault guard.
2. `msclassic2`: the same NTDLL plus the contextual-input
   `imm32.dll` and `winex11.so`.

The two input DLLs are the exact hashes validated in live gameplay, not a
new input implementation. The default launcher, updater, prefix setup and
optional Windows-debugger launcher all reference `msclassic2`.
Normal launches reject an incomplete or mismatched runtime.

| File | SHA-256 |
| --- | --- |
| `ntdll.dll` | `2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d` |
| `winex11.so` | `846f33382d663be8e4d92d0c533044c4b89f4c5c44a347fbf007221b12024bd8` |
| `imm32.dll` | `6ffb4ef5528e48d6e79d7d9da0fe7d0d86f2cfa3ece0847f886942583f28a5aa` |

Source commit, patch, input and output hashes are checked by the builders.
Build/source paths under `/home/ubuntu/.cache/msclassic-build` remain fixed to
reproduce the validated binaries. This is a documented portability boundary.

## Keyboard and Chinese input

Wine's IMM32 patch forwards successful input-context association changes to
the X11 driver. The driver bypasses XIM filtering for keyboard events while
the context is detached; when attached, normal XIM handling remains active.
The player can leave Chinese selected while action keys work outside chat.

The validated binary ABI calls its enable flag
`MSCLASSIC_INPUT_DIAGNOSTIC=1`. Despite that historical name, the flag enables
input-context notification; writing logs separately requires
`MSCLASSIC_INPUT_DIAGNOSTIC_FD`. Normal launches set the first and **omit
the descriptor**, so the fix works without diagnostic recording. Keeping
this ABI avoids changing the tested binaries just to rename an internal flag.

Desktop shortcut handling is separate. The launcher snapshots the per-user
Openbox configuration and LXQt enabled-action states. It preserves Alt+Tab,
Alt+Shift+Tab and LXQt hardware controls, disables other configured shortcuts
for the game session, then restores previous settings on exit. It does not
force Fcitx to English, synthesize keys, or change key-repeat handling.

The shortcut profile lasts for the game session, including when another
window is foreground. It cannot prevent shortcuts consumed by the remote
client or mandatory OS security controls.

## Vendor service and privacy

```text
Game grap64.dll → Wine Service Control Manager
  → game-shipped NGService.exe → game-shipped grap-core64.aes
```

The installer invokes the vendor's own service installation and verifies the
required service baseline. It does not manufacture launch arguments, patch
GRAP, or emulate a Windows kernel-protection driver.

Game launch and client updates share a nonblocking private lock. The updater
downloads public game content only. No signed-in browser profile, game
credential or authenticated URL is part of the repository.

## Optional diagnostics

Input diagnostics record fixed category/timestamp records, never key names,
typed text, window titles or authenticated values. Explicit persistent
logging pins the runtime manifests; legacy development-selection markers do
not enable logging in this release.

Performance profiling is a launcher-owned thread sampling numeric guest
counters once per second. It is not a permanent service or a GPU/FPS profiler.
It is disabled unless explicitly armed and never modifies Proxmox.

Distribution-neutral parsing, privacy and runtime code are separated from the
Lubuntu desktop/package adapter and read-only Proxmox inspection helper.
