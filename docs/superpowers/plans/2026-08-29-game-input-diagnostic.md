# MapleStory input diagnostic and shortcut correction implementation plan

> **For Codex:** Execute this plan in order with the `superpowers:executing-plans` workflow. Apply test-driven development to every behavior change and run the stated verification after each task.

**Goal:** Replace the rejected desktop-wide IME handling, make shortcut suppression transactional through the live LXQt D-Bus daemon, add a private numeric lag profiler, and deploy a side-by-side Wine diagnostic runtime that identifies the game-owned chat signal without logging user input.

**Architecture:** The normal launcher keeps Fcitx in the user's selected state. Openbox is still switched through a reversible user configuration, while LXQt actions are enumerated and toggled through `org.lxqt.global_key_shortcuts` with exact enabled-state restoration. A separate diagnostic Wine runtime records only monotonic timestamps and event categories for XIM filtering, IME status, composition rectangles, and focus. The proven signal—not a keyboard, screen, timing, or game-memory heuristic—will drive a later production Wine patch.

**Tech stack:** Python 3 standard library and `unittest`; Openbox XML; `busctl` against LXQt D-Bus; Bash runtime builder; pinned Wine-TKG 11.10 source; C instrumentation in Wine's X11 driver; Linux `/proc` and PSI metrics.

---

## Task 1: Replace the rejected Fcitx and LXQt lifecycle

**Files:**

- Modify: `tests/test_input_mode.py`
- Modify: `tests/test_runner.py`
- Modify: `src/msclassic/input_mode.py`
- Modify: `src/msclassic/runner.py`
- Modify: `docs/lubuntu-24.04.md`

1. Replace tests for `_transform_lxqt()` and `deactivate_fcitx()` with failing tests for a parser that accepts the fixed `busctl getAllActions` signature, rejects malformed output, classifies XF86 and brightness actions as hardware actions, and returns immutable action snapshots.
2. Add failing lifecycle tests that assert activation calls `enableAction tb ID false` only for enabled non-hardware actions; an originally disabled action remains disabled; a partial failure restores all actions changed so far; and restoration replays every saved boolean exactly.
3. Add failing transaction tests for schema 2 containing the exact Openbox snapshot and LXQt `{id, enabled}` list, stale-state recovery, exact restoration, malformed state, and idempotent restore. Assert that the LXQt configuration file is never read or written and `systemctl` is never invoked.
4. Add failing runner tests proving that no `fcitx5-remote` function is imported or called and that input restoration still runs after normal exit, Wine spawn failure, and forced stop.
5. Implement `LxqtAction`, `_list_lxqt_actions()`, `_set_lxqt_action_enabled()`, `_is_hardware_action()`, and transaction schema 2 in `src/msclassic/input_mode.py`. Invoke `busctl --user call` with fixed arguments, `shell=False`, the inherited session environment, and private/no-input output handling. Use `shlex.split()` for the stable `a{t(ssbss)}` reply and validate the action count and six fields per action before changing state.
6. Remove `deactivate_fcitx()`, LXQt configuration transforms, LXQt file snapshots, and the `systemctl --user restart` path. Keep Openbox atomic writes and `openbox --reconfigure`. Roll back partial LXQt changes immediately; if LXQt D-Bus is unavailable, apply the independently reversible Openbox portion and report that the LXQt portion was unavailable.
7. Update the Lubuntu guide to say that the launcher does not change the selected IME and uses the running LXQt D-Bus daemon rather than editing its configuration.
8. Run `python3 -m unittest tests.test_input_mode tests.test_runner -v`, then `bash scripts/test.sh` and `bash scripts/secret-scan.sh`.
9. Commit with `fix: make desktop input profile transactional` and push `codex/game-input-mode`.
10. Preserve the installed app backup, install this checkpoint from the worktree, run `msclassic input status`, `msclassic input restore`, and verify the user Openbox/LXQt files match their pre-deployment hashes. Do not launch the game yet.

## Task 2: Add a private numeric performance profiler

**Files:**

- Create: `tests/test_profiler.py`
- Modify: `tests/test_cli_integration.py`
- Create: `src/msclassic/profiler.py`
- Modify: `src/msclassic/cli.py`
- Modify: `docs/lubuntu-24.04.md`

1. Write failing tests for parsers of `/proc/meminfo`, `/proc/stat`, `/proc/vmstat`, `/proc/pressure/{cpu,io,memory}`, `/proc/diskstats`, and numeric process totals. Use fixtures that include malformed and missing optional fields.
2. Write a failing schema test requiring one JSON object per line with only a schema number, monotonic timestamp, numeric metrics, and boolean availability flags. Assert recursively that no string values other than fixed metric keys appear in samples.
3. Write failing lifecycle tests for `PerformanceProfiler.start()` and `stop()`: one sample per second, mode `0600`, bounded output directory under `AppPaths.state`, clean stop, no persistent child after Wine exit, and graceful behavior when a procfs source disappears.
4. Implement `src/msclassic/profiler.py` with a sampler thread owned by the launcher process. Aggregate only MapleStory and wineserver CPU ticks/RSS; never record command lines, environment, paths, window data, usernames, or input. Record guest total/available RAM, swap total/free, `pswpin/pswpout`, CPU iowait, PSI totals, selected block-device byte deltas, and a numeric virtio-balloon counter when exposed.
5. Add `msclassic profile start|status|stop` for an explicit standalone controlled run and a launcher option `--profile` that owns the profiler lifecycle. Keep normal launches unchanged.
6. Document the five-minute A/B procedure with the same remote client, resolution, route, map, and approximate player density. State that the profiler observes but never changes Proxmox settings.
7. Run `python3 -m unittest tests.test_profiler tests.test_cli_integration -v`, the full suite, and secret scan.
8. Commit with `feat: add private game performance profiler` and push.

## Task 3: Build a side-by-side privacy-safe Wine input diagnostic

**Files:**

- Create: `tests/test_input_diagnostic.py`
- Modify: `tests/test_cli_integration.py`
- Create: `patches/wine-11.10-msclassic-input-diagnostic.patch`
- Create: `scripts/build-input-diagnostic-wine.sh`
- Create: `src/msclassic/input_diagnostic.py`
- Modify: `src/msclassic/cli.py`
- Modify: `src/msclassic/runner.py`
- Modify: `src/msclassic/runtime.py`
- Modify: `tests/test_runtime.py`
- Modify: `platforms/lubuntu-24.04/install.sh`
- Modify: `docs/lubuntu-24.04.md`

1. Write a failing patch-contract test that clones or uses a supplied exact Wine-TKG source tree at commit `4b12965ca7e78b8e45eee5f835c72963b3ce351d`, applies the diagnostic patch with zero fuzz, and asserts instrumentation exists at `XFilterEvent`, `X11DRV_NotifyIMEStatus`, `X11DRV_SetIMECompositionRect`, and game-window focus transitions.
2. Write failing privacy tests that scan the patch and diagnostic parser. Allowed record fields are `schema`, monotonic nanoseconds, process-local sequence, and one fixed category enum: `xim_filtered_keyboard`, `ime_open`, `ime_closed`, `composition_rect_set`, `composition_rect_clear`, `focus_in`, or `focus_out`. Reject key code, character, text, rectangle coordinates, window title, arguments, URI, token, environment dump, or free-form message fields.
3. Implement the Wine patch behind `MSCLASSIC_INPUT_DIAGNOSTIC=1` and `MSCLASSIC_INPUT_DIAGNOSTIC_FD=<decimal>`. Open no arbitrary path in Wine: the launcher creates a private `0600` file and passes one append-only descriptor. Emit fixed-size records with a monotonic timestamp and enum only. Never alter event routing in this diagnostic runtime.
4. Implement `scripts/build-input-diagnostic-wine.sh`. Verify the locked source commit and base `winex11.so` SHA-256 `5e444a3ef68c4151cdcba3c4653ef43a949cac8dc6615bca940806823fd1a0a5`; use separate source/build directories; apply the existing NTDLL patch and diagnostic patch; build only required X11 artifacts; copy the validated `-msclassic1` runtime to a staged `-msclassic-inputdiag1` directory; replace only its matching `lib/wine/x86_64-unix/winex11.so`; write source, patch, base, and output digests; and atomically rename the staged directory. Never modify the known-good runtime.
5. Add the exact Lubuntu build dependencies to `platforms/lubuntu-24.04/install.sh`, including the X11 development packages discovered by the configure check. The installer remains noninteractive and records installed versions in the audit report.
6. Add diagnostic runtime manifest validation to `runtime.py`. It must require the exact base artifact, source commit, diagnostic patch digest, built `winex11.so` digest, and mode-correct manifest before selection.
7. Add `msclassic input diagnose` in `input_diagnostic.py` and `cli.py`. It creates a timestamped private log under `~/.local/state/maplestory-classic/input-diagnostic/`, launches through the normal authenticated URI path with the side-by-side runtime and diagnostic descriptor, keeps Fcitx unchanged, and restores desktop shortcuts on every exit path. Normal launch, update, and Windows CE keep using the known-good runtime.
8. Add `msclassic input summarize PATH`, producing only counts and relative monotonic transitions. Reject files outside the diagnostic directory, wrong modes, malformed record sizes, unknown categories, and symlinks.
9. Copy the new builder and patch into the installed application in `_install_application()` and test the installed asset digests.
10. Run targeted tests, the full suite, secret scan, `shellcheck` when available, and a builder dry-run through source verification and patch application before compiling.
11. Commit with `feat: add isolated Wine input diagnostic` and push.
12. Preserve the installed app and known-good runtime backups, deploy the diagnostic checkpoint, verify normal `msclassic doctor --json`, verify normal runtime selection remains unchanged, and verify `msclassic input diagnose --help`. Do not launch until those checks pass.

## Task 4: Controlled live observation and evidence report

**Files:**

- Create after the run: `docs/trials/2026-08-29-input-diagnostic.md`
- Modify: `docs/superpowers/specs/2026-08-29-game-input-mode-design.md`

1. Ask the user to initiate the authenticated website launch only after the diagnostic handler is installed. Use AnyDesk or noVNC, not RustDesk.
2. During one run, have the user select Chinese and exercise, in order: chat closed; chat open; harmless dummy Chinese composition; chat closed. Do not ask for or record the composed text.
3. Stop the diagnostic launcher and run the local summarizer. Compare IME-open transitions and composition-rectangle lifetime with the four user-confirmed boundaries. Treat focus events only as a sanity check.
4. Record package/runtime digests, fixed event counts, timing transitions relative to run start, the user's boundary confirmations, and whether one signal matched exactly. Do not include authenticated URIs, input text, account data, process command lines, or raw logs in Git.
5. If neither signal matches exactly, mark the result inconclusive and keep the production runtime unchanged. If one matches, update the design with the proven signal and write a separate TDD implementation plan for paired physical key delivery and out-of-chat XIM suppression.
6. Commit the redacted evidence report and updated design, run the full suite and secret scan, and push. Do not claim the final Chinese gameplay/chat behavior fixed until the later production patch passes live acceptance.

## Task 5: Controlled lag capture

**Files:**

- Create after the run: `docs/trials/2026-08-29-performance-profile.md`

1. Capture two five-minute profiler runs with the same remote client, resolution, route, map, approximate player density, and gameplay route: the known-good normal runtime first, then the eventual production input candidate without diagnostic logging.
2. Summarize numeric CPU, memory, swap, iowait, PSI, disk, and balloon deltas and align them with user-noted stutter timestamps. Keep raw local profiler files out of Git.
3. Only if the data correlates stutter with ballooning, swapping, I/O, or streaming, document a user-visible Proxmox WebUI or guest-level experiment. The project must not apply any Proxmox change.
4. Commit the redacted numeric report, verify the secret scan, and push.

