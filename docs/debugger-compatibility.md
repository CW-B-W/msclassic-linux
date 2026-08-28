# Debugger compatibility

This optional path is for software and processes you are authorized to inspect.
It does not disable, patch, hide from, or bypass MapleStory's GRAP/NGS-X
security chain. An online service may also restrict debugging in its terms;
follow the service rules and coordinate security research with the vendor.

## Supported boundary

Do not attach the native Linux Cheat Engine debugger to this Wine/Unity client.
Use a Windows Cheat Engine installation inside the exact Wine runtime and
prefix used by MapleStory:

```bash
msclassic debugger --windows-ce \
  "/absolute/path/to/Cheat Engine/cheatengine-x86_64.exe"
```

The operator supplies a legitimate Windows Cheat Engine directory. This
project neither downloads nor redistributes it. The command accepts only a
readable `.exe`, uses an argument vector without a shell, forwards a minimal
desktop environment, and forces both of these paths:

```text
Wine:   ~/.local/share/maplestory-classic/tools/
        wine-11.10-staging-tkg-amd64-wow64-msclassic1/bin/wine
Prefix: ~/.local/share/maplestory-classic/prefix-wine1110
```

Using the same prefix is essential: the debugger and target must share the
same Wine server so the Windows debugger API reaches the Windows process.

## Why the native Linux debugger fails

The failure was first observed as Unity's:

```text
Fatal error in GC
SuspendThread loop failed
```

It appeared after native Cheat Engine attached with Linux `ptrace`, even when
Cheat Engine performed no scan. Value scanning was therefore coincidental, not
the trigger.

Wine implements Windows `SuspendThread` and `GetThreadContext` with cooperation
between wineserver, Unix signals, and the Wine threads. A native debugger adds
an independent Linux `ptrace` stop to every thread. In an isolated 64-worker
Windows probe, native Cheat Engine attachment immediately made each
`GetThreadContext` operation fail with Windows error 5. Unity's Boehm garbage
collector uses the same suspend/context pattern for stop-the-world collection
and aborts after its retry loop cannot suspend a thread.

The exact fatal string and retry behavior are visible in
[BDWGC's Windows thread implementation](https://github.com/bdwgc/bdwgc/blob/master/win32_threads.c).
Wine's Linux thread inspection boundary is documented by its
[`server/ptrace.c`](https://github.com/wine-mirror/wine/blob/master/server/ptrace.c)
implementation.

## Isolated validation record

The compatibility trial intentionally excluded MapleStory and GRAP:

1. A synthetic Windows executable created 64 worker threads and a 256 MiB test
   region.
2. It continuously performed `SuspendThread` → `GetThreadContext` →
   `ResumeThread` across all workers.
3. Baseline cycles completed in roughly 11–25 ms with no failures.
4. Native Linux Cheat Engine attachment caused context failures before any
   scan.
5. Windows Cheat Engine in the same Wine server attached, scanned only the
   synthetic marker, remained attached for 10 minutes, detached cleanly, and
   left the loop healthy with zero suspend, context, or resume failures.

The result identifies a debugger/Wine thread-control incompatibility. It is
not evidence of insufficient VM RAM, a Vulkan problem, or GRAP terminating the
client.

The 2026-08-28 lab used native Linux Cheat Engine 7.7.1 for the failing case
and a Windows Cheat Engine 7.5 lab copy for the same-prefix case. The Windows
archive was used only for diagnosis, was not executed as an installer, and is
not part of this repository. Its recorded SHA-256 was
`77ba051fc39d2b2c03d23799d4124617633e8e0a9b906ed91bb8186c1a30f88d`.
Because the versions differ, the result validates the same-prefix technique
and root-cause model; an operator confirmation with their chosen Windows CE
build and the live game remains required.

The exact probe source is
[`diagnostics/suspend-context-probe.c`](../diagnostics/suspend-context-probe.c).
Build it without overwriting an existing file:

```bash
mkdir -p ~/.local/state/maplestory-classic/debugger-lab
bash scripts/build-debugger-probe.sh --output \
  "$HOME/.local/state/maplestory-classic/debugger-lab/suspend-context-probe.exe"
```

Run it only in a disposable Wine prefix, never the live game prefix. The probe
log reports only its own PID, test-region address, cycle timing, worker index,
and Windows error code. A `context_failed` line with `code=5` is the reproduced
native-debugger failure. Delete or retain the lab prefix according to your
normal test-data policy; the project never removes it automatically.

## Recovery after a fatal debugger trial

If the game displays the fatal dialog, close it and wait for the client to
exit. The website handler will refuse another launch while the failed process
still owns the launch lock. If normal exit cannot finish:

```bash
msclassic stop --yes
```

This addresses only the dedicated MapleStory Wine prefix. Relaunch from the
official website after it completes. Never use a global `pkill` or kill an
unrelated Wine server.
