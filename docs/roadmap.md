# Roadmap and expected porting effort

The hard compatibility questions are already answered for the validated VM: official website handoff works, Wine 11.10 supplies the missing Windows API, and WineD3D/OpenGL works over VirGL. Future effort is primarily packaging, graphics-profile validation, and acceptance testing.

| Target | Expected effort | Main work |
| --- | --- | --- |
| Lubuntu 24.04 on Intel/AMD physical hardware, X11 | Low to medium | Add a native-Mesa graphics profile, remove only the VirGL identity requirement for that profile, and complete a live acceptance run. No Proxmox layer is needed. |
| Ubuntu with LXQt on PVE VirGL | Low | Confirm package/session parity with the Lubuntu adapter and run the full acceptance checklist. It may be declared compatible if evidence is identical. |
| Fedora on PVE VirGL | Medium | DNF/multilib package adapter, locale and Chromium policy paths, SELinux checks, then the same VirGL and live acceptance tests. |
| Arch Linux on PVE VirGL | Medium | pacman/multilib adapter, rolling-version lock/drift policy, Chromium integration, and acceptance tests. |
| Fedora or Arch on physical Intel/AMD hardware | Medium | Combine the distribution adapter with the native-Mesa profile and perform the full login/gameplay/reboot validation. |
| Wayland-only desktop | Medium to high | Validate Wine/input/focus and remote desktop under Wayland or provide a supported X11 session. The initial gate intentionally refuses Wayland. |
| 2–4 concurrent PVE VMs | Measurement rather than new compatibility code | Add one VM at a time; measure CPU, RAM, iGPU load, frame pacing, and remote responsiveness. Shared VirGL removes passthrough scarcity but not capacity limits. |

Near-term milestones:

1. Finish post-maintenance character/map and 15-minute gameplay validation on the first VM.
2. Confirm a website launch after a guest reboot without manually invoking doctor.
3. Reproduce on VM 2 and run two VMs concurrently.
4. Test VM 3 and VM 4 sequentially if host capacity remains acceptable.
5. Add a native-Lubuntu graphics profile.
6. Add Fedora, then Arch adapters based on real machines—not speculative package lists.

This project will not add GPU passthrough as the default scaling strategy, automate Beanfun credentials, clone browser sessions, or weaken the protocol/privacy boundary.
