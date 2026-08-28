# Roadmap and expected porting effort

The hard compatibility questions are already answered for the validated VM: official website handoff works, the audited Wine 11.10 profile supplies the required Windows behavior, the vendor GRAP/NGS-X chain reaches a live map, and WineD3D/OpenGL works over VirGL. Future effort is primarily acceptance testing, a path-independent Wine build, packaging, and graphics-profile validation.

| Target | Expected effort | Main work |
| --- | --- | --- |
| Lubuntu 24.04 on Intel/AMD physical hardware, X11 | Low to medium | Add a native-Mesa graphics profile, retain the validated `/home/ubuntu` runtime layout initially, remove only the VirGL identity requirement for that profile, and complete a live acceptance run. No Proxmox layer is needed. |
| Ubuntu with LXQt on PVE VirGL | Low | Confirm package/session parity with the Lubuntu adapter and run the full acceptance checklist. It may be declared compatible if evidence is identical. |
| Fedora on PVE VirGL | Medium | Make the Wine build path-independent, add a DNF/multilib package adapter, handle locale/Chromium policy paths and SELinux, then run the same VirGL/live tests. |
| Arch Linux on PVE VirGL | Medium | Make the Wine build path-independent, add a pacman/multilib adapter and rolling-version drift policy, integrate Chromium, and run acceptance tests. |
| Fedora or Arch on physical Intel/AMD hardware | Medium | Combine the distribution adapter with the native-Mesa profile and perform the full login/gameplay/reboot validation. |
| Wayland-only desktop | Medium to high | Validate Wine/input/focus and remote desktop under Wayland or provide a supported X11 session. The initial gate intentionally refuses Wayland. |
| 2–4 concurrent PVE VMs | Measurement rather than new compatibility code | Add one VM at a time; measure CPU, RAM, iGPU load, frame pacing, and remote responsiveness. Shared VirGL removes passthrough scarcity but not capacity limits. |

Near-term milestones:

1. Confirm a website relaunch after closing the same-prefix Windows debugger,
   and a website launch after guest reboot without manually invoking doctor.
2. Reproduce on VM 2 and run two VMs concurrently.
3. Test VM 3 and VM 4 sequentially if host capacity remains acceptable.
4. Validate Sunshine/Moonlight; keep RustDesk excluded from gameplay unless its
   Linux held-key delivery is fixed upstream.
5. Add a native-Lubuntu graphics profile.
6. Make the patched Wine build path-independent.
7. Add Fedora, then Arch adapters based on real machines—not speculative package lists.

This project will not add GPU passthrough as the default scaling strategy, automate Beanfun credentials, clone browser sessions, or weaken the protocol/privacy boundary.
