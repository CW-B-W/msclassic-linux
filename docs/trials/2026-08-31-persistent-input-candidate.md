# Input candidate 2: deployment audit, 2026-08-31

## Scope and status

This trial fixes **candidate selection**, not a proven Chinese-input fix.
The Wine patch remains the same candidate introduced in commit `dc0bbb6`.
No game files, GRAP, graphics settings, Proxmox settings, or key-repeat
handling are changed by this deployment.

The desired gameplay result is: Chinese remains selected, but `C` attacks
outside chat; inside chat it composes Bopomofo. That result remains pending
user confirmation. A build, a launcher test, or an initialization event is
not evidence that the gameplay requirement passes.

## Why the last test was not testing candidate 2

The read-only audit found game PID `2269764` using the normal `msclassic1`
runtime. Both `winex11.so` and `imm32.dll` mapped into that process came from
the normal runtime. No diagnostic environment flag was set, and diagnostic
status was `inactive`.

The candidate was installed separately, but `input diagnose` selected it for
one launch only. A subsequent website launch returned to the normal runtime.
This was a deployment/test-workflow failure, not the player's responsibility.
The old candidate-2 log contained only one context-detached event and one
focus-in event; it did not establish a gameplay/chat boundary.

## Reproduce the deployment

Use the development branch and installed candidate build described in the
[Lubuntu quick start](../quick-start-lubuntu-pve.md#contextual-ime-diagnostic-development-only).
After installing the updated project application:

```bash
msclassic input diagnose --persistent
msclassic input diagnostic-status
```

Expected state before launch: `enabled`. The private persistent selection
pins the candidate name and manifest, including the two input-module hashes.
Every launch revalidates the build. Invalid/missing files or a changed build
pin cause a refusal, not silent fallback to a different runtime.

Close the existing game and launch normally from the official website.
This does not patch already-running processes. No browser restart is needed.
The persistent selection survives game exits and VM reboots until explicitly
disabled. A separate private category-only diagnostic log is made each run.

## Verify the live game, not just installed files

```bash
msclassic input diagnostic-status
for game_pid in $(pgrep -x Maplestory_Clas); do
    ps -p "$game_pid" -o pid,comm,etime
    readlink -f "/proc/$game_pid/exe"
    tr '\0' '\n' < "/proc/$game_pid/environ" |
        rg '^(MSCLASSIC_INPUT_DIAGNOSTIC|MSCLASSIC_INPUT_DIAGNOSTIC_FD|WINEPREFIX)='
    rg -o '/[^ ]+/(winex11\.so|imm32\.dll)$' "/proc/$game_pid/maps" | sort -u
done
```

Expected: `capturing`, diagnostic flag `1`, and both mapped input modules
under `wine-11.10-staging-tkg-amd64-wow64-msclassic-inputcandidate2`.
Do not print command-line arguments or authenticated browser URLs.

Candidate SHA-256 values:

| Module | SHA-256 |
| --- | --- |
| `lib/wine/x86_64-unix/winex11.so` | `846f33382d663be8e4d92d0c533044c4b89f4c5c44a347fbf007221b12024bd8` |
| `lib/wine/x86_64-windows/imm32.dll` | `6ffb4ef5528e48d6e79d7d9da0fe7d0d86f2cfa3ece0847f886942583f28a5aa` |

Use the live mapped paths with `sha256sum` when recording a test. Avoid
assuming that an installed candidate means the current process loaded it.

## Tests and rollback

Four new CLI/lifecycle tests were run first and failed because the persistent
option did not exist, then passed after implementation. A real-child launcher
test additionally exercises two successive authenticated-runner invocations:
both select the candidate and inherit an open diagnostic file descriptor.
The suite verifies private fresh logs, explicit stop during capture, invalid
runtime refusal, and changed/malformed build-pin refusal. These are deployment
tests, not tests of the game's UI or Fcitx behavior.

Review identified an incomplete build pin: the input manifest alone did not
pin the inherited NTDLL patch. A regression test reproduced that gap and
passed after including the base runtime manifest. The final suite passed
155 tests; independent review and the repository secret scan also passed.

## Live deployment evidence

At 2026-08-31 04:02 Asia/Taipei, the updated installed launcher matched the
worktree source checksums. Persistent selection was enabled, the old game
was stopped through the dedicated-prefix stop command, and a new game was
launched through the official GamePass/Google/account-selection flow.

The fresh game PID was `2284826`. Its `/proc` executable path and both mapped
input modules were under `msclassic-inputcandidate2`, rather than
`msclassic1`. `MSCLASSIC_INPUT_DIAGNOSTIC=1` and its diagnostic descriptor
were present. Status reported `capturing` with persistent selection retained.
The loaded module paths had the candidate SHA-256 values listed above.

This confirms **candidate deployment in the live process**. It does not
confirm that gameplay keys bypass Chinese composition or that chat still
works; those require the user test below. The game was left open for testing.

### Rollback

To revert future launches:

```bash
msclassic input diagnostic-stop
```

This leaves the current game alone. Close it and relaunch to use `msclassic1`.
The known-good Wine directory and previous private diagnostic logs are retained.

## User test after live-runtime verification

1. With chat closed and Chinese selected, press `C`: it must attack, with no
   `ㄏ` composition appearing.
2. Open chat and use Left Shift to select Chinese if necessary; `C` must
   compose `ㄏ` in chat.
3. Close chat with Chinese still selected; `C` must attack again.

If this fails with candidate 2 confirmed in the live process, record it as a
candidate failure. Do not infer success from zero filtered-key events or
assume input-context attachment reliably follows chat without evidence.
