# Optional debugger compatibility

The game does not require a debugger. This optional launcher is for software
and processes you are authorized to inspect; follow the service's rules and
coordinate security research with the vendor. It does not bypass GRAP/NGS-X.

## Windows debugger in the game prefix

Supply your own legitimate Windows Cheat Engine directory:

```bash
msclassic debugger --windows-ce \
  "/absolute/path/to/Cheat Engine/cheatengine-x86_64.exe"
```

The command selects the normal `msclassic2` Wine runtime and dedicated
`~/.local/share/maplestory-classic/prefix-wine1110` prefix. It accepts a
readable Windows executable, uses no shell, and does not inherit browser
secrets. The project neither downloads nor redistributes Cheat Engine.

Windows CE 7.5 attachment, a content-neutral read-only scan, clean detach and
continued gameplay were validated with the previous base runtime. The input
release retains the same NTDLL and Wine server, but the combined release's
debugger/relaunch acceptance still needs confirmation. Do not interpret this
as a guarantee about arbitrary CE versions or debugger operations.

## Native Linux ptrace is unsupported

Do not attach native Linux Cheat Engine's debugger to this Wine/Unity client.
The observed failure is:

```text
Fatal error in GC
SuspendThread loop failed
```

Native debugger stops can interfere with Wine's Windows thread-control
coordination. Attachment alone reproduced the failure, without scanning.
Use the same-prefix Windows debugger path for authorized compatibility work;
increasing VM RAM is not an established fix for this incompatibility.

## Recovery

Close the failed game normally. If it cannot exit:

```bash
msclassic stop --yes
```

This stops only the dedicated game prefix, including same-prefix tools.
After it completes, launch again through the official website. Do not use a
global Wine kill command or expose authenticated launch arguments in logs.
