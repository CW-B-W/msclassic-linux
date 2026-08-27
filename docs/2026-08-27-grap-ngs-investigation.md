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
- A constrained x86-64 NTDLL frame-walk patch prevents the earlier Unity/GRAP-adjacent crash and lets the client reach server selection.

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

The code now stops and waits for the dedicated Wine server before reading persistent registry state, rejects incomplete service baselines, invokes only the vendor installer, and refuses authenticated launch if NGS state is incomplete. Live GRAP process and map-entry acceptance remain pending.

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

## Deployed/runtime divergence

The repository currently locks the stock `wine-11.10-staging-tkg-amd64-wow64` artifact. The deployed handler was temporarily changed during diagnosis to use a persistent candidate named `wine-11.10-staging-tkg-amd64-wow64-msclassic1` and to capture `+process,+loaddll` diagnostics.

Therefore the checked-in project does not yet reproduce the exact runtime that reached server selection. Before calling the project reproducible, it must provide an auditable build/apply path for the NTDLL patch and remove the temporary deployed-only runner divergence.

## Investigation order

Each trial changes one variable and records before/after evidence:

1. Verify a clean or repaired prefix reaches a complete Wine service baseline (`RpcSs`, `PlugPlay`, and `services.exe` access).
2. Run the vendor-supplied `NGService_Install.bat` or its exact `NGService.exe -install` command inside that prefix; do not construct an `NGS` registry entry manually.
3. Verify the resulting service name, image path, installed file, and start/query behavior.
4. Launch once with bounded `+service,+process,+loaddll` diagnostics and verify the updater/core creation boundary.
5. Verify `grap-core64.aes` remains alive, creates its named pipe, and prevents the forced-close condition through map entry.
6. Convert the confirmed setup into an idempotent installer action and an offline doctor check.
7. Add failing-first tests for incomplete-prefix rejection, vendor-service provisioning, redacted diagnostics, and relaunch behavior.
8. Restore quiet normal-launch diagnostics, update the quick start and troubleshooting guide, and run the full regression suite.

## Rejected shortcuts

- Do not `chmod +x` GRAP files as the proposed fix; Wine is already loading PE files with mode 0644.
- Do not manually invent the core PID/event-handle arguments.
- Do not create fake NGS registry entries.
- Do not disable, replace, or patch GRAP/NGS-X.
- Do not change several Wine, graphics, and service variables in one trial.
- Do not change Proxmox while investigating this guest-prefix failure.
