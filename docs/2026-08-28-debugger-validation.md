# Windows debugger compatibility validation — 2026-08-28

## Scope

This supervised trial tested only whether an ordinary Windows debugger can
coexist with MapleStory Classic under Wine. It did not bypass or modify
GRAP/NGS-X, target a game value, set a breakpoint or watchpoint, write memory,
freeze a value, or conceal the debugger.

The operator was authorized to inspect the local process. Online-service rules
and coordinated-disclosure requirements remain applicable to any future
security research.

## Exact environment

- MapleStory runtime: repository-verified Wine 11.10 profile
  `wine-11.10-staging-tkg-amd64-wow64-msclassic1`.
- Prefix: `~/.local/share/maplestory-classic/prefix-wine1110`.
- Debugger: Windows Cheat Engine 7.5, launched by `msclassic debugger` in that
  exact runtime and prefix.
- Debugger executable SHA-256:
  `ac9bcc7813c0063bdcd36d8e4e79a59b22f6e95c2d74c65a4249c7d5319ae3f6`.
- Debugger interface: `1`, CE's ordinary Windows debugger.
- Concurrent vendor security process: `grap-core64.aes` remained alive.
- Guest: Lubuntu 24.04 X11 on the validated Proxmox VirGL profile.

The Windows CE lab archive itself is not redistributed. Its recorded SHA-256
and provenance boundary are documented in
[Debugger compatibility](debugger-compatibility.md).

## Procedure and observations

### 1. Attach without action

The operator selected only `Maplestory_Classic.exe` and executed:

```lua
debugProcess(1)
```

For ten minutes, no scan, breakpoint, watchpoint, or memory edit was performed.
At 30-second checkpoints:

- MapleStory, GRAP, and CE process counts remained one each;
- no `Fatal error` / `SuspendThread loop failed` window appeared;
- memory PSI `some avg10` remained `0.00`;
- available memory remained approximately 4.8–5.0 GiB;
- CE RSS remained approximately 281 MiB.

Local audit ID: `20260828-094415-windows-ce-live-no-action`.

### 2. Content-neutral read-only scan

CE performed one `Exact Value`, `4 Bytes` scan for the arbitrary constant
`123456789`. No result was selected, browsed, frozen, or written.

For five minutes after scan completion:

- MapleStory, GRAP, Unity Crash Handler, and CE remained alive;
- no fatal window appeared;
- memory PSI remained `0.00`;
- available memory remained approximately 4.8–5.0 GiB;
- the operator confirmed that movement, attack, and normal gameplay still
  worked.

Local audit ID: `20260828-095139-windows-ce-live-readonly-scan`.

### 3. Clean detach

The operator executed:

```lua
detachIfPossible()
```

CE returned its debugger interface to nil. During a further two-minute
observation, MapleStory and GRAP remained alive, no fatal window appeared,
memory PSI stayed `0.00`, and the operator confirmed normal gameplay.

Local audit ID: `20260828-095951-windows-ce-live-detach`.

## Result

For this exact build and runtime, same-prefix Windows CE passed ordinary
debugger attachment, a content-neutral read-only scan, clean detach, and
continued gameplay. This directly avoids the native Linux CE `ptrace` conflict
that made Wine's Windows thread-context operations fail and eventually caused
Unity's garbage collector to abort.

This is a debugger-compatibility reference, not a claim that untested debugger
operations work. Breakpoints, watchpoints, memory modification, value freezing,
and other game-state operations remain unvalidated and outside this result.
