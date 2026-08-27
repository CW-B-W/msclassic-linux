# MS Classic Linux Clean Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a clean `msclassic-linux` repository that reproducibly installs and launches MapleStory Classic on a Lubuntu 24.04 Proxmox VirGL VM without manual post-reboot doctor commands.

**Architecture:** A distribution-neutral Python core owns protocol parsing, privacy, artifact verification, Wine launch, audit, and normalized graphics checks. A Lubuntu 24.04 adapter owns guest packages and desktop integration, while Proxmox support remains read-only checks plus operator-executed WebUI instructions. The official website invokes a scoped NGM handler that automatically performs the current-boot graphics gate before starting pinned Wine 11.10 through WineD3D/OpenGL.

**Tech Stack:** Python 3.12 standard library, Bash, Git, Wine 11.10 staging/TkG WoW64, WineD3D/OpenGL, Mesa VirGL, QEMU VirtIO-GPU, Chromium policy, freedesktop MIME handlers, `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-27-ms-classic-linux-clean-project-design.md`

## Global Constraints

- Lubuntu 24.04 on Proxmox VirGL is the only initial supported target.
- Executable project code never mutates Proxmox or runs `qm set`.
- Git never contains game files, runtime archives, Wine prefixes, browser profiles, credentials, cookies, or authenticated launch values.
- Wine artifact is `wine-11.10-staging-tkg-amd64-wow64`, 97357652 bytes, SHA-256 `5355cff72783e30f96e3e47aef440b0408a7bf550e53a00c8df139186f37ea25`.
- Game rendering uses WineD3D/OpenGL, not DXVK/Vulkan.
- Chromium permits `ngm` only from `https://maplestoryclassic.beanfun.com`.
- Every mutating installation has a non-mutating plan.
- First website launch after reboot approves graphics automatically; manual `doctor` is troubleshooting only.
- All subprocesses use argument vectors and `shell=False`; private arguments never enter logs or exports.

---

### Task 1: Bootstrap clean repository and provenance

**Files:**
- Create: `/home/ubuntu/ms-classic-linux/.git`
- Create: `README.md`, `.gitignore`, `pyproject.toml`
- Create: `src/msclassic/__init__.py`, `tests/test_package.py`
- Create: `docs/architecture.md`
- Create: approved spec and this plan under `docs/superpowers/`

**Interfaces:**
- Consumes empty `git@github.com:CW-B-W/msclassic-linux.git`.
- Produces importable `msclassic.__version__ == "0.1.0"` and canonical docs.

- [ ] **Step 1: Clone and inspect the empty repository**

```bash
git clone git@github.com:CW-B-W/msclassic-linux.git /home/ubuntu/ms-classic-linux
git -C /home/ubuntu/ms-classic-linux remote -v
```

Expected: SSH origin and no tracked files.

- [ ] **Step 2: Write failing package smoke test**

```python
import unittest
import msclassic

class PackageTests(unittest.TestCase):
    def test_public_version_is_defined(self):
        self.assertEqual(msclassic.__version__, "0.1.0")
```

- [ ] **Step 3: Verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_package -v`

Expected: FAIL because `msclassic` is absent.

- [ ] **Step 4: Add skeleton and metadata**

Set `__version__ = "0.1.0"`. Configure Python `>=3.12` and console entry `msclassic = "msclassic.cli:entrypoint"`. Ignore bytecode, virtualenvs, downloads, prefixes, game trees, and candidate reports. README states unofficial status, no shipped game files, initial target, and no authentication/anti-cheat bypass.

- [ ] **Step 5: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_package -v
git add .gitignore README.md pyproject.toml src tests docs
git commit -m "chore: bootstrap msclassic-linux project"
```

---

### Task 2: Add locked artifacts and paths

**Files:**
- Create: `versions.lock`
- Create: `src/msclassic/lockfile.py`, `src/msclassic/paths.py`
- Create: `tests/test_paths_lockfile.py`

**Interfaces:**
- Produces `Artifact`, `load_versions(path)`, `verify_file(path, artifact)`, and `AppPaths.from_environment(env)`.
- Prefix is `<XDG_DATA_HOME>/maplestory-classic/prefix-wine1110`; client is `~/Games/MapleStoryClassic`.

- [ ] **Step 1: Write failing tests**

Assert exact XDG paths and digest verification. Reject non-HTTPS URLs, unknown keys, invalid digests/sizes/algorithms, and non-schema-1 files.

- [ ] **Step 2: Verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_paths_lockfile -v`

- [ ] **Step 3: Implement frozen dataclasses and exact parsing**

Accept only `version`, `url`, `algorithm`, `digest`, and `size`. Populate exactly `[wine]` and `[nxdl]` with validated source-workspace values.

- [ ] **Step 4: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_paths_lockfile -v
git add versions.lock src/msclassic/lockfile.py src/msclassic/paths.py tests/test_paths_lockfile.py
git commit -m "feat: pin Wine runtime and application paths"
```

---

### Task 3: Add protocol and privacy boundary

**Files:**
- Create: `src/msclassic/protocol.py`, `src/msclassic/redaction.py`
- Create: `tests/test_protocol_redaction.py`, `scripts/secret-scan.sh`

**Interfaces:**
- Produces `LaunchRequest`, `parse_launch_uri`, `redact_text`, and `assert_export_safe`.

- [ ] **Step 1: Write failing tests**

Cover official NGM and NexonPlug, game code 2982, one-time decoding, literal plus, duplicate/missing fields, NUL/fragments, 65,536-byte URI, 128-token, and 4,096-byte token limits. Shell metacharacters remain argv data.

- [ ] **Step 2: Verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.test_protocol_redaction -v`

- [ ] **Step 3: Implement bounded parsing and export guards**

Use `urlsplit` and explicit fields, never `shlex`, `eval`, or a shell. Redact complete authenticated URIs and named authentication/session values. Scanner excludes its definitions/tests and detects realistic NGM/NexonPlug values.

- [ ] **Step 4: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_protocol_redaction -v
bash scripts/secret-scan.sh
git add src/msclassic/protocol.py src/msclassic/redaction.py tests/test_protocol_redaction.py scripts/secret-scan.sh
git commit -m "feat: validate and redact authenticated launches"
```

---

### Task 4: Add platform adapters and graphics doctor

**Files:**
- Create: `src/msclassic/platforms/base.py`, `lubuntu_2404.py`, `__init__.py`
- Create: `src/msclassic/commands.py`, `src/msclassic/doctor.py`
- Create: `tests/test_platforms.py`, `tests/test_doctor.py`, graphics fixtures

**Interfaces:**
- Produces `PlatformAdapter`, `select_platform`, `GraphicsReport`, `collect_graphics_report`, and `evaluate_launch_graphics`.

- [ ] **Step 1: Write failing adapter tests**

Ubuntu 24.04 selects `lubuntu-24.04`. Fedora, Arch, unknown Ubuntu, and mismatched explicit choices raise fixed unsupported-platform errors.

- [ ] **Step 2: Write failing graphics tests**

X11, at least 1280×720, render-node access, and OpenGL renderer containing `virgl` pass. llvmpipe, missing access, Wayland, and low resolution fail. Vulkan remains diagnostic only.

- [ ] **Step 3: Verify failures**

Run: `PYTHONPATH=src python3 -m unittest tests.test_platforms tests.test_doctor -v`

- [ ] **Step 4: Implement adapter and allowlisted diagnostics**

Declare validated amd64/i386 Mesa diagnostics, locales, curl, archive tools, Python, xdg, notification, and rsync packages. Use fixed executable allowlists, bounded outputs, and timeouts.

- [ ] **Step 5: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_platforms tests.test_doctor -v
git add src/msclassic/platforms src/msclassic/commands.py src/msclassic/doctor.py tests
git commit -m "feat: add Lubuntu platform and VirGL doctor"
```

---

### Task 5: Build two-stage Lubuntu installer

**Files:**
- Create: `src/msclassic/installer.py`
- Create: `platforms/lubuntu-24.04/install.sh`, `maplestory-classic.reg`
- Create: `tests/test_installer.py`

**Interfaces:**
- Produces `build_install_plan(paths, artifacts, source, adapter)` and `execute_install(plan, graphics, dry_run, operation)`.

- [ ] **Step 1: Write failing plan/archive tests**

Packages come first; read-only client source is accepted; disk requirement is client plus three-times artifacts plus 2 GiB; only Wine/nxdl appear; invalid cache quarantines; traversal, devices, FIFOs, and escaping links reject.

- [ ] **Step 2: Write failing prefix timeout tests**

A 60-second wineboot timeout passes only with `system.reg`, `user.reg`, and `drive_c/windows/system32`, followed by that prefix's wineserver `-k/-w`.

- [ ] **Step 3: Verify failures**

Run: `PYTHONPATH=src python3 -m unittest tests.test_installer -v`

- [ ] **Step 4: Implement audited actions**

Use HTTPS-only curl, exact verification, private temporaries, atomic replacement, client copy, narrow registry settings, i386 apt setup, and locale generation. `--dry-run` exits before sudo, dpkg, apt, network, or filesystem mutation.

- [ ] **Step 5: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_installer -v
bash platforms/lubuntu-24.04/install.sh --dry-run --source /media/ubuntu/MapleStoryClassic
git add src/msclassic/installer.py platforms/lubuntu-24.04 tests/test_installer.py
git commit -m "feat: add audited Lubuntu installation plan"
```

Expected: zero mutations and only pinned Wine 11.10 plus nxdl.

---

### Task 6: Add automatic approval and Wine website handler

**Files:**
- Create: `src/msclassic/approval.py`, `runner.py`, `cli.py`
- Create: `desktop/msclassic-ngm.desktop.in`
- Create: `platforms/lubuntu-24.04/chromium-policy.json`
- Create: `tests/fixtures/fake-wine`
- Create: `tests/test_approval.py`, `test_runner.py`, `test_cli_integration.py`

**Interfaces:**
- Produces `ensure_current_boot_approval(paths, collector)`, `build_wine_command`, `run_authenticated`.
- Produces CLI `doctor`, `plan`, `install`, and `handle-url`.

- [ ] **Step 1: Write failing approval tests**

Matching boot stamp skips collection. Missing/stale stamp collects once and atomically writes mode 0600. Failure writes no stamp and returns fixed error. Authenticated request never reaches collector/errors.

- [ ] **Step 2: Write failing isolation tests**

Assert pinned Wine/prefix, `WINEDEBUG=-all`, zh_TW locale, minimal PATH/environment, absent inherited secrets/debug variables, devnull stdio, `shell=False`, and `start_new_session=True`.

- [ ] **Step 3: Write failing handler/policy tests**

Handler parses, auto-approves, launches, registers NGM and both NexonPlug cases with rollback, and uses fixed notify-send failure text. Policy contains exactly one NGM entry for the official origin.

- [ ] **Step 4: Verify failures**

Run: `PYTHONPATH=src python3 -m unittest tests.test_approval tests.test_runner tests.test_cli_integration -v`

- [ ] **Step 5: Implement approval, launch, status, and registration**

Use a mode-0600 nonblocking launch lock, automatic approval, Wine artifact stamp, writable client, and exact argv. Status contains only schema, fixed stage, and integer exit. Manual doctor creates the same stamp proactively.

- [ ] **Step 6: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_approval tests.test_runner tests.test_cli_integration -v
git add src/msclassic desktop platforms/lubuntu-24.04/chromium-policy.json tests
git commit -m "feat: launch Wine automatically from the official website"
```

---

### Task 7: Add controlled operations and audit

**Files:**
- Create: `src/msclassic/updater.py`, `src/msclassic/audit.py`
- Create: `tests/test_updater.py`, `tests/test_audit.py`
- Modify: `src/msclassic/cli.py`

**Interfaces:**
- Produces update/check/stop, `TrialRecorder`, and CLI `update`, `stop`, `reproduce`, `uninstall`.

- [ ] **Step 1: Write failing updater tests**

Require nxdl verification, bounded JSON, 1 GiB headroom, explicit apply, exclusive locking, and pinned wineserver only after `--yes`; no global pkill.

- [ ] **Step 2: Write failing audit tests**

Require one changed variable, allowlisted commands, sanitized output, deterministic reports, and rejection of secret exports.

- [ ] **Step 3: Implement and verify**

Run: `PYTHONPATH=src python3 -m unittest tests.test_updater tests.test_audit tests.test_cli_integration -v`

Uninstall keeps client and prefix; updates remain manual.

- [ ] **Step 4: Commit**

```bash
git add src/msclassic tests
git commit -m "feat: add controlled operations and audit reports"
```

---

### Task 8: Add read-only Proxmox support and docs

**Files:**
- Create: `platforms/proxmox/readonly-preflight.sh`, `pve-virgl.toml`
- Create: `tests/test_proxmox.py`
- Create: `docs/quick-start-lubuntu-pve.md`, `troubleshooting.md`, `adding-a-platform.md`, `roadmap.md`
- Create: `docs/2026-08-27-successful-launch.md`

**Interfaces:**
- Produces only host `check` and `webui-plan`; documents current workflow and future adapter evidence.

- [ ] **Step 1: Write failing safety tests**

Only read-only commands exist; running VM/existing args reject; PVE 9.1/9.2, packages, renderer, and device properties check; fake mutation commands never run.

- [ ] **Step 2: Implement script and profile**

Record renderD128, hostmem 2G, blob/venus, q35/OVMF, 1366×768, Wine 11.10, WineD3D/OpenGL. WebUI plan leaves all changes to operator.

- [ ] **Step 3: Write documentation**

Cover dependencies, visible PVE actions, guest plan/install, automatic first launch, GamePass flow, maintenance, acceptance, scale-out, troubleshooting layers, adapter evidence, and unvalidated roadmap targets.

- [ ] **Step 4: Verify and commit**

```bash
PYTHONPATH=src python3 -m unittest tests.test_proxmox -v
git add platforms/proxmox docs tests/test_proxmox.py
git commit -m "docs: add guarded Proxmox and platform guidance"
```

---

### Task 9: Verify and publish

**Files:**
- Create: `scripts/test.sh`, `reports/reference/README.md`
- Modify: `README.md`

**Interfaces:**
- Produces one complete verification command and reviewed GitHub branch.

- [ ] **Step 1: Add test driver and final README links**

Test driver runs verbose unittest discovery with `PYTHONPATH=src` and bytecode disabled. README links all operator/developer docs and successful trial.

- [ ] **Step 2: Run fresh verification**

```bash
bash scripts/test.sh
bash scripts/secret-scan.sh
git diff --check
bash platforms/lubuntu-24.04/install.sh --dry-run --source /media/ubuntu/MapleStoryClassic
```

Expected: all tests/scan/diff pass; dry-run is zero-mutation with only Wine 11.10 and nxdl.

- [ ] **Step 3: Run non-authenticated runtime probe**

Use synthetic arguments only. Confirm no Wine 11.0 UI Automation abort. Do not claim website acceptance while maintenance blocks NGM generation.

- [ ] **Step 4: Commit verification assets**

```bash
git add README.md scripts/test.sh reports/reference/README.md
git commit -m "test: complete clean-project verification"
```

- [ ] **Step 5: Audit tree and push**

```bash
git status --short
git ls-files
git log --oneline --decorate -10
git push -u origin HEAD
```

Expected: clean tree, no archives/game/prefix/browser/probe/secret content, and GitHub contains the reviewed initial project. Live website acceptance remains pending until maintenance ends.
