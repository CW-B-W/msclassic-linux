# MS Classic Linux

Unofficial personal-project tooling for playing MapleStory Classic on Linux.
The current target is **Lubuntu 24.04, X11, on a Proxmox VM with shared VirGL
graphics**. GPU passthrough is not required.

The game runs through Wine 11.10 staging/TkG with two reproducible compatibility
patches. Direct3D is translated by WineD3D to OpenGL, then Mesa VirGL shares the
host GPU. The official website handles login; the unmodified game and its
vendor security services handle the game session.

## What works

- Official GamePass → Google login and automatic website-to-game launch.
- Server/character selection and live-map gameplay.
- Chinese chat with Fcitx 5, while alphabetic action keys still work outside
  chat when Chinese remains selected.
- Conflicting desktop shortcuts suppressed during the game; Alt+Tab and
  Alt+Shift+Tab preserved; previous settings restored on exit.
- Keyboard play through Proxmox noVNC and AnyDesk.
- Initial public-client download, importing existing files, and explicit updates.

The normal runtime is `wine-11.10-staging-tkg-amd64-wow64-msclassic2`.
Input handling is enabled by default. **No diagnostic command is needed to
activate it, and no manual doctor command is needed after reboot.**
Diagnostics and performance logging are optional and off by default.

This is a single-VM validated profile, not a promise of identical behavior on
every machine. Fresh-VM, post-reboot, long-session and multi-VM acceptance
remain explicit checks in [validation](docs/validation.md). Crowded-map
stutter is not yet resolved. Fedora, Arch, physical hardware and Wayland are
[future targets](docs/roadmap.md).

## Install

First complete the [Proxmox dependencies, WebUI configuration and guest
setup](docs/quick-start-lubuntu-pve.md). The current reproducible build requires
the guest user `ubuntu`, home `/home/ubuntu`, and Lubuntu's X11 session.

Inside the prepared guest:

```bash
git clone --branch main --single-branch https://github.com/CW-B-W/msclassic-linux.git
cd msclassic-linux
bash scripts/test.sh
bash platforms/lubuntu-24.04/install.sh --dry-run --download-client
bash platforms/lubuntu-24.04/install.sh --download-client
```

Alternatively, replace `--download-client` with
`--source /media/ubuntu/MapleStoryClassic` to import legitimate existing files.
Dry-run makes no package, network or filesystem changes. Real installation
verifies downloads, builds and checks the compatibility DLLs, prepares the
dedicated Wine prefix and vendor service, and registers the launch handler.

Open [the official website](https://maplestoryclassic.beanfun.com/Main) in
Chromium, select GamePass → Google → your account, then launch the game.
Do not copy signed-in browser profiles or authenticated launch URLs between VMs.

## Everyday commands

```bash
msclassic doctor --json           # troubleshooting, not a reboot ritual
msclassic update                  # check for a game update
msclassic update --apply          # download/apply an update while game is closed
msclassic stop --yes              # stop only the dedicated game Wine prefix
msclassic input status            # inspect temporary desktop-shortcut profile
msclassic input restore           # recover shortcuts after an interrupted game
msclassic profile start           # optionally record the next launch's performance
msclassic profile status
msclassic profile stop
msclassic uninstall              # remove desktop integration; retain game/prefix
```

Optional input diagnostics and the authorized Windows-debugger launcher are
described in [troubleshooting](docs/troubleshooting.md) and
[debugger compatibility](docs/debugger-compatibility.md).

## Documentation

- [Complete Lubuntu/Proxmox setup](docs/quick-start-lubuntu-pve.md)
- [Architecture and runtime verification](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Validation and remaining acceptance checks](docs/validation.md)
- [Optional debugger compatibility](docs/debugger-compatibility.md)
- [Adding another platform](docs/adding-a-platform.md)
- [Roadmap](docs/roadmap.md)
- [Development and contribution workflow](CONTRIBUTING.md)

## Boundaries and credits

The project never changes Proxmox. The operator performs all host changes in
Proxmox WebUI. It does not change the OS default web browser, redistribute the
game/Wine payloads, store credentials, or bypass authentication or anti-cheat.
Authenticated launch arguments never enter normal status or audit logs.

The original macOS community workflow informed this Linux implementation:
[CitrusGate](https://github.com/dspp779/CitrusGate),
[CyderBits](https://github.com/dspp779/CyderBits), and the
[community guide](https://forum.gamer.com.tw/C.php?bsn=7650&snA=1037767).
Wine is sourced from the pinned
[Kron4ek Wine-TkG repository](https://github.com/Kron4ek/wine-tkg).
Third-party tools and the game retain their respective licenses.
