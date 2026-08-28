# Game input mode for Lubuntu 24.04

## Purpose

MapleStory Classic is playable in the dedicated Wine prefix, but two desktop
layers still interfere with normal play:

- When Fcitx is active for Chinese composition, it receives alphabetic keys
  before the game.  For example, `C` opens Pinyin composition instead of
  attacking.
- Openbox and LXQt global shortcuts can consume game combinations.  The
  observed example is Openbox's `Alt+Space` client-menu binding, which
  prevents the game's jump-and-attack combination.

This feature supplies a temporary, per-game **Game input mode** for the
official browser-to-Wine launch path.  It is deliberately not a general
keyboard grab and does not make any Proxmox or system-wide configuration
change.

## User experience and policy

When the official `NexonPlug` handler launches the game, it must:

1. Put Fcitx in its inactive (English/direct-input) state on a best-effort
   basis.
2. Install the temporary desktop shortcut profile before Wine is started.
3. Restore the user's exact prior desktop shortcut configuration after Wine
   exits, including if Wine fails to spawn.

The user may activate Fcitx temporarily to type Chinese in MapleStory chat,
then deactivate it again before resuming action keys.  The launcher must not
reactivate Fcitx on exit: the user may have deliberately changed the state
while playing.

Game input mode preserves `Alt+Tab` and `Alt+Shift+Tab` for application
switching.  It must remove every other configurable Openbox and LXQt global
keyboard combination from the active temporary profile, including `Alt+Space`,
`Alt+F4`, desktop-switching bindings, Meta/Super bindings, launchers,
screenshots, lock/task-manager/terminal bindings, and panel actions.  It does
not disable mouse input, multimedia/power hardware keys, Fcitx's own input
method toggle, kernel security-attention controls, or shortcuts consumed by a
remote-viewer client before they reach the guest.

`Alt+Tab` is intentionally the normal escape route.  A second recovery route
is `msclassic input restore` from a different terminal, SSH session, or the
Proxmox console.  This command must be safe to run repeatedly.

## Supported scope

The implementation targets the current graphical session only when all of
the following are true:

- X11 is in use;
- Openbox is the window manager;
- `lxqt-globalkeysd` is running; and
- the user's XDG configuration and runtime directories are available.

That is the supported Lubuntu 24.04 desktop environment.  On another desktop
environment, no shortcut profile is applied; the official launch still works
and reports the unsupported input-profile state through `msclassic input
status`.  This restriction keeps the platform-neutral game setup separate
from desktop-specific keyboard policy.

## Components

### Input profile manager

Add a focused module responsible only for desktop input policy.  It exposes:

- `status(paths)`: reports inactive, active, stale, unavailable, or malformed
  state without printing launch arguments, account information, or other
  sensitive data.
- `activate(paths, environment)`: validates the supported session, makes a
  private backup transaction, writes the temporary profile, reloads Openbox
  and LXQt global shortcuts, and verifies that the profile is active.
- `restore(paths, environment)`: restores the exact prior user files (or
  removes a generated file when none existed), reloads both services, and
  deletes the transaction only after success.
- `deactivate_fcitx(environment)`: runs the fixed argv
  `fcitx5-remote -c` only when the executable and session D-Bus environment
  are available.  A missing daemon, command, or non-zero result is recorded
  as unavailable and never blocks a game launch.

Private transaction data belongs below
`~/.local/state/maplestory-classic/input-profile/`, uses mode `0700` for the
directory and `0600` for files, and records file contents plus whether each
file existed before activation.  Writes are atomic.  At a later launch or an
explicit `restore`, a stale transaction is restored before any new profile is
created.

### Openbox temporary profile

The manager uses a user-level `~/.config/openbox/rc.xml`; it never edits
`/etc/xdg/openbox/rc.xml`.  It starts from the user's existing file when
present, otherwise from the current system file.  It removes all `<keybind>`
elements from the `<keyboard>` section except `A-Tab` and `A-S-Tab`.

It reloads this profile with `openbox --reconfigure` in the active X11
environment.  Restoration writes back the byte-for-byte prior user file (or
removes the temporary user file) and then reconfigures Openbox again.

### LXQt temporary profile

The manager reads the user configuration at
`~/.config/lxqt/globalkeyshortcuts.conf`.  The temporary version preserves
only non-combination hardware controls (for example volume) and disables all
configured combinations.  It does not invent or remap keys.  In particular,
it disables the current `Control+Alt+...` and `Meta+...` actions rather than
trying to compete with them from Wine.

The user-level configuration is backed up transactionally and reloaded by
restarting only the user-session `lxqt-globalkeyshortcuts` service.  The
manager must verify that `lxqt-globalkeysd` becomes available again before it
continues.  A reload failure triggers immediate restoration of both desktop
files and produces a clear, non-secret error; the game must not start with a
partially applied profile.

### Launcher integration and CLI

`run_authenticated` is the sole automatic integration point.  After its
existing validation and before Wine starts, it deactivates Fcitx best-effort,
activates the input profile, and uses `finally` to restore the profile after
the Wine subprocess finishes or fails to start.

Add two non-destructive CLI operations:

```text
msclassic input status
msclassic input restore
```

`status` never modifies configuration.  `restore` is idempotent and may be
used after a crash, forced game stop, or interrupted remote session.  Neither
command requires access to or emits a browser launch URI.

## Failure handling

- Fcitx is optional: its failure does not prevent launch or profile cleanup.
- Unsupported or malformed desktop configuration is a fail-open condition:
  leave the desktop unchanged, launch the game, and report it through
  `status` rather than guessing how to rewrite another desktop environment.
- An Openbox or LXQt activation/reload failure is fail-closed for the profile:
  restore the original configuration first, then launch the game without an
  active profile.  It must never leave a half-applied desktop profile.
- If the game or launcher is terminated without cleanup, a private stale
  transaction remains.  `input restore` and the next official launch detect
  and restore it before doing anything else.
- `msclassic stop --yes` remains a dedicated-prefix recovery tool and does
  not change input configuration.  The launcher's `finally` cleanup handles
  the normal result of that forced Wine shutdown.

## Tests and acceptance checks

Unit tests must cover:

- Fcitx command construction, absence, non-zero result, and non-fatal error
  handling;
- Openbox selective binding transformation, retaining only `A-Tab` and
  `A-S-Tab`;
- LXQt combination disabling while retaining hardware-only entries;
- atomic backup/restore, no-prior-file restoration, idempotent restore, and
  stale-transaction recovery;
- unsupported-session fail-open behavior;
- runner ordering: prepare Fcitx, activate profile, run Wine, restore in all
  result paths; and
- CLI exit codes and output redaction for `input status` and `input restore`.

Manual acceptance is required on VM 80001 after the game is closed and
restarted through Chromium's normal GamePass path.  Test both noVNC and
AnyDesk:

1. Held arrows, `C`, Space, Alt, and `Alt+Space` reach the game.
2. `Alt+Tab` and reverse `Alt+Shift+Tab` still switch applications.
3. Meta/Super, `Ctrl+Alt+T`, `Ctrl+Alt+L`, screenshots, desktop switching,
   and the Openbox client menu do not interrupt play while the profile is
   active.
4. Fcitx can be toggled on for Chinese chat and off for gameplay.
5. Game exit restores all prior shortcuts exactly; forced stop and an
   explicit `msclassic input restore` also restore them.

RustDesk is excluded from input acceptance because held-arrow loss has
already been isolated to that client, while noVNC and AnyDesk have passed the
baseline keyboard test.

## Non-goals

- No GPU, Proxmox, host, or `/etc` configuration changes.
- No manipulation, bypass, or disabling of MapleStory, GRAP, NGS, or any
  other anti-cheat component.
- No claim that the solution controls shortcuts intercepted by a remote
  client or mandatory OS security controls.
- No automatic inference of when a Unity chat box has focus; Fcitx is a
  deliberate manual chat-mode toggle.
