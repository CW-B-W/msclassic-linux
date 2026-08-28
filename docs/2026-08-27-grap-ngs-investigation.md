# MapleStory Classic GRAP / NGS-X investigation — 2026-08-27

## Scope and safety boundary

This record covers compatibility with the unmodified Nexon NGS-X / GRAP security components shipped with MapleStory Classic. The goal is to let the official client install, start, and communicate with its security service under Wine. It does not disable, patch, impersonate, or bypass the security module.

Do not include authenticated `ngm://` or `NexonPlug://` requests, session values, browser profiles, cookies, or credentials in diagnostics. No Proxmox change is part of this investigation.

## Acceptance target

A Windows 10 reference run has three visible game-related processes:

1. `Maplestory_Classic.exe`
2. `grap-core64.aes`
3. `UnityCrashHandler64.exe`

The `.aes` suffix does not make `grap-core64.aes` a Linux or encrypted-container executable. It is a PE32+ x86-64 Windows GUI executable. It must be launched through the vendor's NGS service workflow with live session arguments; manually executing it or adding a Linux executable bit is not a valid substitute.

Completion requires all of the following:

- the official website launches the client through the private desktop handler;
- `grap64.dll` loads in the game process;
- the Wine prefix contains a working Windows service infrastructure;
- the vendor `NGS` service is installed and can start;
- `NGService.exe` launches the updater and `grap-core64.aes` with the current game PID and event handle;
- the GRAP named-pipe session becomes active;
- the client passes server/character selection and enters a map without the security-module forced-close message;
- a normal exit and a second website launch work;
- no authenticated values appear in project logs or reports.

## Confirmed working layers

- Shared VirGL graphics without GPU passthrough.
- WineD3D to VirGL/OpenGL rendering at 1366x768.
- Chromium `ngm` handoff from the official Beanfun page.
- GamePass / Google browser authentication.
- Wine starts `Maplestory_Classic.exe` with the authenticated argument vector.
- Unity starts `UnityCrashHandler64.exe`.
- The native game plugin `grap64.dll` loads.
- A constrained x86-64 NTDLL frame-walk patch prevents the earlier Unity/GRAP-adjacent crash and lets the client reach and remain in a live map.
- The complete Wine service prefix starts the game-shipped `NGService.exe`, which starts `grap-core64.aes` normally.
- `Maplestory_Classic.exe`, `grap-core64.aes`, and `UnityCrashHandler64.exe` coexist in the successful run, matching the Windows reference process set.

## Original failure

The client reaches server selection and then reports the security-module forced-close condition. During that run:

- `Maplestory_Classic.exe` was present;
- `UnityCrashHandler64.exe` was present;
- `grap-core64.aes` was absent;
- `NGService.exe` and `grap-updater.aes` were absent;
- `grap64.log` changed, while `grap-core64.log` did not;
- Wine recorded `Failed to open RpcSs service`;
- Wine process tracing recorded no attempt to create a GRAP helper process.

The game was stopped with `SIGTERM` after the failure. It exited promptly, and no forced kill was required.

## Corrected prefix finding

The installed handler uses:

```text
~/.local/share/maplestory-classic/prefix-wine1110
```

An earlier ad-hoc registry query accidentally inspected the older experimental `prefix` directory. The conclusion below was rechecked against the active `prefix-wine1110` prefix.

Before repair, the active prefix contained only two `System\\ControlSet001\\Services` registrations:

```text
MountMgr
Tcpip\\Parameters
```

It had no `RpcSs`, `PlugPlay`, or `NGS` service registration and no installed `C:\\ProgramData\\Nexon\\NGS\\NGService.exe`. The older experimental prefix contained approximately forty standard Wine service registrations, including `RpcSs` and `PlugPlay`.

This is consistent with the live `Failed to open RpcSs service` error and places the first proven break before GRAP core creation.

## Confirmed cause and repair

The original installer initialized the prefix with `wineboot -u`, but accepted a 60-second timeout as success when these three coarse artifacts existed:

- `system.reg`
- `user.reg`
- `drive_c/windows/system32`

Those artifacts can exist before Wine has registered its standard services. The original active prefix satisfied that coarse test but lacked the service infrastructure required by NGS. The hypothesis was:

> The initial `wineboot` timed out, the installer accepted a partially initialized prefix, and `grap64.dll` cannot open or install the NGS service because the Wine SCM/RPC layer is incomplete.

The hypothesis was confirmed in isolated and live-prefix trials:

- a fresh prefix created with the patched Wine candidate and `WINEDLLOVERRIDES=mscoree,mshtml=` completed without optional Mono/Gecko prompts;
- it persisted the standard Wine service baseline after `wineserver -k` and `wineserver -w`;
- the exact game-shipped `NGService.exe -install` command returned zero;
- Wine registered `NGS` and installed the 4,299,144-byte broker at `C:\\ProgramData\\Nexon\\NGS\\NGService.exe`;
- the old partial prefix could not be made trustworthy by an in-place update, so it was retained as a rollback directory and replaced by a separately built and fully validated prefix;
- the active replacement now passes offline checks for `RpcSs`, `PlugPlay`, `NGS`, and the installed broker.

The code now stops and waits for the dedicated Wine server before reading persistent registry state, rejects incomplete service baselines, invokes only the vendor installer, and refuses authenticated launch if NGS state is incomplete.

## Live validation after repair

The fresh authenticated GamePass launch on 2026-08-27 produced this safe, name-only lifecycle:

```text
Maplestory_Classic.exe
UnityCrashHandler64.exe
NGService.exe               # short-lived broker start
grap-core64.aes             # remained alive
```

`grap64.dll` had three mappings in the MapleStory process. `NGService.exe` spawned at 21:07:00 and exited after handing off to GRAP; `grap-core64.aes` remained alive with MapleStory and Unity Crash Handler throughout the observation. The operator selected a character and entered a live map without the prior security-module forced-close message.

No process argument vector was printed because MapleStory and GRAP command lines can contain private per-session values.

## Debugger failure is separate from GRAP bootstrap

A later native Linux Cheat Engine attachment produced Unity's `Fatal error in
GC: SuspendThread loop failed`. It also reproduced when the debugger merely
remained attached and performed no scan. At failure, `grap-core64.aes` was
still alive and the VM had several GiB of available memory; there was no OOM
event or memory-pressure stall.

The failure was reproduced without MapleStory or GRAP using a harmless Windows
probe with 64 worker threads. Native Linux `ptrace` attachment made Wine's
Windows `GetThreadContext` calls fail, whereas Windows Cheat Engine running
inside the same Wine server attached, scanned the probe's test buffer, remained
attached for 10 minutes, and detached with zero probe failures. This supports a Wine/debugger thread-control
conflict, not a GRAP attribution. See
[Debugger compatibility](debugger-compatibility.md).

A subsequent supervised live MapleStory trial confirmed the boundary. Windows
CE debugger interface 1 remained attached for 10 minutes, completed one
content-neutral read-only scan, remained stable for five more minutes, and
detached cleanly. GRAP stayed alive and the operator confirmed normal gameplay
after both scan and detach. Breakpoints and memory modification were not tested.

## CyderBits comparison

CyderBits does not manually launch `grap-core64.aes`. Its recorded successful path is:

```text
Maplestory_Classic.exe
  -> grap64.dll
  -> Wine/CrossOver Service Control Manager
  -> NGService.exe
  -> WinVerifyTrust(grap-updater.aes, grap-core64.aes)
  -> CreateProcess(grap-updater.aes, grap-core64.aes)
  -> \\.\pipe\grap-core64\2982
  -> active GRAP session
```

CyderBits records a live core command line shaped as:

```text
grap-core64.aes <game-code> <game-pid> <event-handle>
```

For Classic, the observed game code is `2982`. The PID and event handle are per launch and must come from the normal service workflow. Cyder's application layer has no game-specific code that replaces this chain; its Wine/CrossOver runtime and prefix permit the vendor workflow to run.

## Runtime divergence resolved

The repository still locks the unmodified `wine-11.10-staging-tkg-amd64-wow64` archive as its base artifact. It now also contains:

- the exact source patch at `patches/wine-11.10-ntdll-frame-walk-page-fault-guard.patch`;
- the exact upstream source commit `4b12965ca7e78b8e45eee5f835c72963b3ce351d`;
- a fail-closed builder at `scripts/build-patched-wine.sh`;
- independent stock-artifact, patch, source-file, final NTDLL, and runtime-manifest checks;
- a separate installed profile named `wine-11.10-staging-tkg-amd64-wow64-msclassic1`;
- normal quiet launcher code shared by the repository and deployed application.

An end-to-end reproduction created a fresh runtime and matched the known-good patched NTDLL SHA-256 exactly:

```text
2bb7613fead5e50b4fa47e65f1d2856a5b8d8301a58a806d1a7214451004123d
```

Wine embeds absolute source paths in NTDLL, so profile v1 pins `/home/ubuntu/.cache/msclassic-build`. This is reproducible on the current Lubuntu VM template and deliberately fails early for another home path. A path-independent profile is future distribution portability work.

## Investigation order

Each trial changes one variable and records before/after evidence:

1. Exit normally and relaunch from the website; separately confirm recovery
   after a failed debugger-attached process is fully stopped.
2. Reboot the guest and repeat without manually running doctor.
3. Reproduce on VM 2 before increasing concurrency.

## Rejected shortcuts

- Do not `chmod +x` GRAP files as the proposed fix; Wine is already loading PE files with mode 0644.
- Do not manually invent the core PID/event-handle arguments.
- Do not create fake NGS registry entries.
- Do not disable, replace, or patch GRAP/NGS-X.
- Do not change several Wine, graphics, and service variables in one trial.
- Do not change Proxmox while investigating this guest-prefix failure.
