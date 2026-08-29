# Game input mode for Lubuntu 24.04 — corrected design

## Status and correction

This revision supersedes the first design. The first implementation treated
Chinese input as a manual mode switch: it deactivated Fcitx at launch and
required the player to return to English before using alphabetic action keys.
That does not meet the required user experience.

The required behavior is contextual inside the game:

- With the chat field closed, physical gameplay keys must work even while the
  desktop input method remains Chinese. Alphabetic keys such as `C` must not
  start composition or display candidates.
- With the chat field open, the same keys must produce Chinese composition and
  must not trigger gameplay actions.
- Left Shift remains the ordinary desktop Chinese/English selector, but the
  player must not need to switch back to English merely to resume gameplay.

The first implementation also restarts the LXQt shortcut service. On the
reference VM the original daemon is owned by `lxqt-session`; the attempted
systemd start fails because that daemon still owns
`org.lxqt.global_key_shortcuts`. This reload mechanism is replaced below.

## Evidence and root cause

Wine 11.10 processes X11 events in this order:

1. `XFilterEvent()` gives each event to XIM/Fcitx.
2. A filtered event is discarded from Wine's normal event path.
3. Only unfiltered events reach `X11DRV_KeyEvent()` and update Wine's physical
   keyboard state.

Fcitx filters alphabetic key presses while Chinese input is active, so Wine's
keyboard/DirectInput state never receives them. Non-composition keys such as
the arrows remain unfiltered, which explains why movement was unrelated and
already worked. Cyder's macOS engine uses Wine's native macOS input driver;
its published IME patch only hides IME-only keyboard-layout identifiers and
is not a Linux/X11 solution.

The game-specific signal that distinguishes its chat field from general
gameplay must be observed rather than guessed. Candidate signals are Wine's
IME-open notification and composition-rectangle updates. A diagnostic run
will determine whether either signal follows chat open/close exactly.

## Scope and constraints

The implementation targets Lubuntu 24.04 with X11, Openbox, LXQt, Fcitx 5,
and the project's pinned Wine 11.10 runtime. It is enabled only by the
MapleStory launcher and must not change the behavior of unrelated Wine
applications or the Windows Cheat Engine launcher.

It makes no Proxmox, host, GPU-passthrough, `/etc`, game-file, GRAP, NGS, or
anti-cheat change. Any Proxmox recommendation is presented for the user to
apply visibly in WebUI; the project never applies it.

RustDesk remains excluded from keyboard acceptance because its held-arrow
failure was isolated previously. Use noVNC or AnyDesk for controlled input
tests and keep the same remote client between performance comparisons.

### Current rollout state

The feature branch and the locally installed launcher currently contain the
rejected first input implementation, but the game is closed, its transaction
is inactive, and the original desktop configuration has been restored. The
first implementation is not merged into the reference branch. Before another
official game launch, implementation must deploy a diagnostic launcher that
removes the forced Fcitx deactivation and the failed LXQt restart. If work is
interrupted before that deployment, the user should not use the current
official handler for acceptance testing.

## Diagnostic-first architecture

### Isolated diagnostic runtime

The working runtime remains untouched. The project builds a side-by-side
diagnostic runtime from the same locked Wine source and base artifact. The
diagnostic change is gated by a MapleStory-specific environment flag and
records only event categories and monotonic timestamps:

- an XIM-filtered keyboard event occurred;
- Wine changed IME open/closed state;
- Wine received or cleared a composition rectangle;
- the game window gained or lost focus.

It must not record key codes, characters, composed text, window titles,
launch arguments, account data, URIs, tokens, cookies, or authentication
values. The log is private mode `0600` beneath
`~/.local/state/maplestory-classic/input-diagnostic/` and is removed from the
normal launch path after the experiment.

One controlled run exercises four states in order: Chinese selected with chat
closed, chat opened, Chinese composition in chat using non-sensitive dummy
text, and chat closed again. The diagnostic result selects the implementation
signal:

- If IME-open state tracks chat boundaries exactly, it is authoritative.
- Otherwise, if composition-rectangle lifetime tracks them exactly, that is
  authoritative.
- If neither signal tracks chat boundaries, no Enter/Escape, screen-coordinate,
  OCR, timing, or process-memory heuristic is shipped. The diagnostic is
  reported as inconclusive and the production runtime remains unchanged until
  a reliable application signal is found.

### Final Wine/X11 behavior

After a reliable chat signal is proven, the production Wine patch is enabled
only when the launcher sets a fixed MapleStory input environment flag. It
maintains two independent paths:

- Physical key press/release state continues to reach Wine even when XIM
  filters the corresponding X11 event. Press and release must remain paired
  so keys cannot stick.
- XIM composition is accepted only while the proven chat signal is active.
  Outside chat, filtered composition is reset or suppressed while the physical
  key continues through the game input path.

Inside chat, MapleStory's existing chat state is expected to suppress action
handling just as it does on Windows; this is an acceptance condition, not an
assumption. If an action occurs while composing chat, the patch is rejected
and the working runtime is restored.

The patch is applied to the exact pinned source commit, verified by source and
patch digests, built reproducibly, and recorded in the runtime manifest with
the existing NTDLL frame-walk patch. Runtime validation checks both patched
artifacts. Installation stages a new runtime and replaces the selected
runtime only after every digest and smoke test passes; rollback retains the
last known-good runtime.

## Desktop shortcut profile

### Openbox

Continue using a temporary user-level Openbox profile, never `/etc`. Preserve
only `Alt+Tab` and `Alt+Shift+Tab`; disable `Alt+Space`, `Alt+F4`, and other
Openbox combinations while the game runs. `openbox --reconfigure` activates
and restores the profile. Exact prior bytes and file existence are restored
transactionally.

### LXQt

Do not rewrite the LXQt configuration file or restart its daemon. Query the
running daemon through `org.lxqt.global_key_shortcuts`, snapshot each action's
enabled state, and call its documented `enableAction(id, false)` operation for
non-hardware shortcuts. Preserve XF86 multimedia, brightness, power, and
other hardware controls. Restore every saved action state through the same
D-Bus interface after Wine exits.

If D-Bus enumeration or any state change fails, restore every action already
changed and continue without the LXQt portion. Openbox and LXQt transactions
are independently reversible. `msclassic input restore` remains idempotent
and recovers stale state after interruption.

The launcher no longer forces `fcitx5-remote -c`. The user's selected input
method remains intact because the Wine patch, rather than a desktop-wide mode
switch, owns gameplay-versus-chat routing.

## Performance diagnosis

The input and shortcut code performs work only at launch and exit; it must not
poll during gameplay. A separate private profiler samples once per second and
records only numeric system and process metrics:

- game and wineserver CPU and resident memory totals;
- guest available RAM and assigned total RAM;
- swap occupancy and swap-in/swap-out deltas;
- CPU iowait, pressure-stall totals, and disk throughput;
- whether the virtio balloon driver changes the guest memory target, when that
  counter is available.

The current post-run evidence is suggestive but not conclusive: the guest saw
about 7.4 GiB total RAM, 510 MiB of a 512 MiB swap file was occupied, and the
kernel previously reported repeated `update_balloon_size_func` CPU stalls.
The controlled run must correlate stutter with these metrics before any RAM,
swap, remote-streaming, or Proxmox recommendation is made.

Compare the current working runtime and the candidate runtime using the same
remote client, resolution, map, and approximate player density. Diagnostic
logging is not used for the final performance comparison.

## Failure handling and privacy

- Diagnostic and candidate runtimes are side-by-side; a failed build or test
  cannot overwrite the working runtime.
- Unsupported desktops and unavailable D-Bus interfaces fail open without
  editing user files.
- Partial shortcut changes roll back immediately. Stale transaction state is
  recovered before a new launch.
- A Wine or input failure restores the last known-good runtime.
- Logs contain no input values or authenticated launch material and pass the
  repository secret scan before commit.
- The game and its security components are neither patched nor injected into.

## Automated verification

Tests must cover:

- static application of both Wine patches to the pinned source;
- environment scoping so unrelated Wine launches and Windows CE remain
  unchanged;
- paired physical press and release delivery for XIM-filtered keys;
- suppression or reset of XIM outside the proven chat signal and normal
  composition inside it;
- absence of key values and authenticated material from diagnostic output;
- D-Bus action enumeration, selective disabling, partial-failure rollback,
  exact restoration, stale recovery, and idempotent restore;
- Openbox preservation of only forward and reverse application switching;
- launcher cleanup after normal exit, failed spawn, and forced Wine stop;
- runtime manifest and digest validation with rollback; and
- profiler output schema and numeric-only redaction.

The full unit and integration suite and secret scan must pass before a live
launch.

## Live acceptance on VM 80001

Using noVNC or AnyDesk:

1. Select Chinese input while the chat field is closed. Hold and tap the
   alphabetic action keys, including `C`; actions work and no composition or
   candidate window appears.
2. Open chat without changing the desktop input method. Chinese composition
   and candidate selection work, and the same keys do not trigger actions.
3. Close chat without switching to English. Gameplay keys immediately work
   again.
4. `Alt+Space` reaches the game; no window menu appears.
5. `Alt+Tab` and `Alt+Shift+Tab` still switch applications. Other configurable
   Openbox and LXQt shortcuts do not interrupt play.
6. Game exit and `msclassic stop --yes` restore every shortcut exactly;
   repeated `msclassic input restore` is harmless.
7. Two five-minute comparisons use the same remote client, resolution, route,
   and approximate map population. The final input path adds no persistent
   helper process, increases combined game and wineserver CPU by no more than
   one percentage point on average, and produces no new user-observed stutter.
   If stutter correlates instead with ballooning, swapping, I/O, or remote
   encoding, document that separately rather than attributing it to the
   keyboard patch.

Only after all seven checks pass may the feature branch be merged and the
installed launcher updated as the reproducible reference implementation.

## Non-goals

- No manual English-before-gameplay requirement.
- No chat detection based on Enter or Escape assumptions, pixels, OCR, timing,
  or game-memory inspection.
- No interception of shortcuts owned by the remote client or mandatory kernel
  security controls.
- No GPU passthrough or automatic Proxmox modification.
- No anti-cheat bypass, game modification, or debugger integration.
