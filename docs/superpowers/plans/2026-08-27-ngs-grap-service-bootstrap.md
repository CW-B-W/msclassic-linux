# NGS / GRAP Service Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a noninteractive, idempotent Wine-prefix bootstrap that installs the unmodified Nexon NGS service and lets the official game launch `grap-core64.aes` automatically.

**Architecture:** Prefix initialization suppresses optional Wine Mono/Gecko prompts and accepts completion only when Wine's SCM/RPC baseline exists. Installation then invokes the game-shipped `NGService.exe -install` command through the pinned Wine runtime, stops the dedicated prefix to flush persistent state, and validates the registered service plus installed broker before the runner can launch authenticated game arguments.

**Tech Stack:** Python 3.12 standard library, `unittest`, Wine 11.10 staging/TkG WoW64, Wine registry files, Nexon's unmodified `NGService.exe`, Bash verification scripts.

**Spec:** `docs/2026-08-27-grap-ngs-investigation.md`

## Global Constraints

- Do not modify, disable, replace, impersonate, or bypass NGS-X / GRAP.
- Do not log authenticated browser URIs, launch arguments, credentials, cookies, or session values.
- Do not change Proxmox; this repair is entirely inside the Lubuntu guest and dedicated Wine prefix.
- Do not manually fabricate an `NGS` registry entry or launch `grap-core64.aes` with guessed arguments.
- Use only the game-shipped `Maplestory_Classic_Data/Plugins/x86_64/grap/NGService.exe -install` workflow.
- Normal launch must remain automatic from the official Beanfun website and must not require running doctor after reboot.

---

### Task 1: Reject partial Wine prefixes and initialize noninteractively

**Files:**
- Modify: `src/msclassic/installer.py`
- Modify: `tests/test_installer.py`

**Interfaces:**
- Produces: `_prefix_initialized(prefix: Path) -> bool`, requiring registry files, `system32`, `RpcSs`, and `PlugPlay`.
- Produces: Wine prefix commands with `WINEDLLOVERRIDES=mscoree,mshtml=` during setup.

- [ ] **Step 1: Write the failing partial-prefix test**

Add a test that creates the current coarse artifacts but only a `MountMgr` service and asserts `_prefix_initialized(...)` is false. Add a complete fixture with literal `RpcSs` and `PlugPlay` registry headings and assert it is true.

- [ ] **Step 2: Run the targeted tests and verify the partial-prefix assertion fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_installer.InstallerTests.test_prefix_completion_requires_wine_rpc_and_plugplay_services -v
```

Expected: FAIL because the current implementation accepts the partial prefix.

- [ ] **Step 3: Implement the minimal completion check and noninteractive setup environment**

Parse service headings from `system.reg` and require the literal service names `RpcSs` and `PlugPlay`. Add `WINEDLLOVERRIDES=mscoree,mshtml=` only to Wine setup/provisioning commands so the optional add-on dialogs cannot block unattended installation.

- [ ] **Step 4: Replace the old timeout-acceptance expectation**

Update the timeout test so a timed-out complete prefix remains recoverable, while a partial prefix is rejected. Assert the actual subprocess environment contains the noninteractive override.

- [ ] **Step 5: Run installer tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_installer -v
```

Expected: all installer tests pass.

### Task 2: Provision and verify the vendor NGS service

**Files:**
- Create: `src/msclassic/ngs.py`
- Create: `tests/test_ngs.py`
- Modify: `src/msclassic/installer.py`
- Modify: `tests/test_installer.py`
- Modify: `tests/test_cli_integration.py`

**Interfaces:**
- Produces: `NgsState` with `rpcss_registered`, `plugplay_registered`, `ngs_registered`, and `broker_installed` booleans.
- Produces: `inspect_ngs_state(paths: AppPaths) -> NgsState` using only offline prefix/client state.
- Produces: installer action `install_ngs`, ordered after `import_registry`.

- [ ] **Step 1: Write failing offline-state tests**

Use literal Wine registry fixtures to prove partial, service-only, broker-only, and complete NGS states are distinguished. The production change caught is accepting a prefix whose service key or installed broker is missing.

- [ ] **Step 2: Run the new tests and verify import/behavior failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_ngs -v
```

Expected: FAIL because `msclassic.ngs` does not exist.

- [ ] **Step 3: Implement the offline state inspector**

Read `system.reg` with bounded error handling, parse only service headings, and check the exact installed broker path `drive_c/ProgramData/Nexon/NGS/NGService.exe`. Never read or emit game logs or authenticated arguments.

- [ ] **Step 4: Write the failing installer-action tests**

Assert that `install_ngs` follows `import_registry`, invokes exactly the client-relative `NGService.exe` with the single `-install` argument, uses no shell, and fails if post-install state is incomplete.

- [ ] **Step 5: Implement vendor provisioning**

Run the exact game-shipped broker installer with the pinned Wine runtime and dedicated prefix. Stop and wait for only that prefix's wineserver after the installer exits so `system.reg` is flushed, then require the complete `NgsState`.

- [ ] **Step 6: Run NGS, installer, and CLI tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_ngs tests.test_installer tests.test_cli_integration -v
```

Expected: all selected tests pass.

### Task 3: Refuse authenticated launch when NGS persistence is incomplete

**Files:**
- Modify: `src/msclassic/runner.py`
- Modify: `tests/test_runner.py`
- Modify: `docs/troubleshooting.md`

**Interfaces:**
- Consumes: `inspect_ngs_state(paths: AppPaths) -> NgsState`.
- Produces: fixed, secret-free `RunnerError` before starting Wine when the prefix service baseline or NGS broker is incomplete.

- [ ] **Step 1: Write the failing runner guard test**

Create an otherwise valid runtime/client fixture with incomplete NGS state. Assert `run_authenticated` raises before `subprocess.run` receives the private launch arguments.

- [ ] **Step 2: Run the targeted runner test and verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_runner.RunnerTests.test_launch_refuses_incomplete_ngs_state_before_private_spawn -v
```

Expected: FAIL because the current runner launches without checking NGS persistence.

- [ ] **Step 3: Implement the minimal launch guard**

Call the offline inspector after runtime/client validation and before constructing or spawning the authenticated command. Return only a fixed remediation message.

- [ ] **Step 4: Update troubleshooting**

Document that a security-module forced close with no `grap-core64.aes` points to prefix/NGS bootstrap, not Vulkan or Linux file permissions. Provide secret-free service-state checks.

- [ ] **Step 5: Run runner and redaction tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_runner tests.test_protocol_redaction tests.test_cli_integration -v
```

Expected: all selected tests pass.

### Task 4: Repair and verify the live dedicated prefix

**Files:**
- Update: `docs/2026-08-27-grap-ngs-investigation.md`
- Create locally, never commit: a timestamped backup under `~/.local/state/maplestory-classic/prefix-backups/`

**Interfaces:**
- Consumes: the same noninteractive prefix and NGS provisioning functions used by installation.
- Produces: active `prefix-wine1110` with standard Wine services and registered vendor `NGS` broker.

- [ ] **Step 1: Stop only the dedicated prefix and back up its registry files**

Use the candidate runtime's `wineserver -k` and `-w` with the exact `WINEPREFIX`. Copy `system.reg`, `user.reg`, and `userdef.reg` to a mode-0700 timestamped backup directory before mutation.

- [ ] **Step 2: Complete Wine initialization noninteractively**

Run the candidate `wineboot -u` with `WINEDLLOVERRIDES=mscoree,mshtml=` and require a zero exit plus `RpcSs` and `PlugPlay` persistence.

- [ ] **Step 3: Install the vendor NGS service**

Run the game-shipped `NGService.exe -install`, stop the dedicated wineserver to flush state, and require the `NGS` service plus ProgramData broker.

- [ ] **Step 4: Record a sanitized before/after report**

Record only service counts, required service booleans, command exit codes, installed broker size, runtime identity, and timestamps. Run `bash scripts/secret-scan.sh` on the report.

### Task 5: End-to-end GRAP acceptance and project handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/2026-08-27-successful-launch.md`
- Modify: `docs/quick-start-lubuntu-pve.md`
- Modify: `docs/2026-08-27-grap-ngs-investigation.md`

**Interfaces:**
- Produces: a reproducible website-to-map acceptance record and documented relaunch behavior.

- [ ] **Step 1: Deploy the tested project code to the local handler**

Use the project's normal installer deployment path. Preserve the candidate patched runtime until its reproducible build/apply path is committed; do not silently switch the live test back to stock Wine.

- [ ] **Step 2: Launch from the official website**

Use GamePass, Google, the existing browser account, and the `bradhk` game account. Do not paste or record the generated authenticated URL.

- [ ] **Step 3: Verify the process and IPC boundary**

Confirm `Maplestory_Classic.exe`, `UnityCrashHandler64.exe`, `NGService.exe`, and `grap-core64.aes` appear as expected. Use bounded process/service diagnostics; do not inspect or alter GRAP memory or protocol contents.

- [ ] **Step 4: Verify gameplay and relaunch**

Pass server selection, character selection, and map entry; remain active for at least 15 minutes; exit normally; launch a second time from the website.

- [ ] **Step 5: Run the full project verification**

Run:

```bash
bash scripts/test.sh
bash scripts/secret-scan.sh README.md docs reports/reference
git diff --check
```

Expected: all tests pass, secret scan passes, and no whitespace errors are reported.

- [ ] **Step 6: Commit and push the verified branch**

Commit only source, tests, redacted reports, and documentation. Do not commit the game, Wine binaries, prefixes, raw Wine logs, or browser/authentication material. Push `codex/initial-implementation` to the configured GitHub remote.

