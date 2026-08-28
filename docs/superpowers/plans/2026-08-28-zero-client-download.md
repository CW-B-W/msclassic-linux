# Zero-Client Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable an explicit initial MapleStory Classic client download on a fresh supported Lubuntu VM.

**Architecture:** Add a download module for verified nxdl operations, defensive staging normalization, validation, and atomic promotion. Wire it into existing installer actions and expose exact source/download selection through the CLI and Lubuntu wrapper.

**Tech Stack:** Python 3.12 standard library, Bash, unittest.

**Spec:** `docs/superpowers/specs/2026-08-28-zero-client-download-design.md`

## Global Constraints

- Keep source imports unchanged. Download mode is explicit, does not handle credentials, and does not modify Proxmox or anti-cheat components.
- Real installation requires exactly one client source. Download dry-run neither contacts nxdl nor creates a client tree.
- Check and download only with checksum-verified locked nxdl. Require total manifest bytes plus 1 GiB available under `~/Games`.
- Use only `~/Games/.MapleStoryClassic.download`; validate before atomic promotion to `~/Games/MapleStoryClassic`.
- Reject links, special files, paths outside staging, malformed Windows-backslash components, and collisions. Preserve failed staging and never replace an invalid final client.

---

### Task 1: Download primitives

**Files:**

- Create: `src/msclassic/client_download.py`
- Create: `tests/test_client_download.py`
- Modify: `src/msclassic/updater.py`, `tests/test_updater.py`

**Interfaces:**

- Produces: `ClientDownloadError`, `DownloadCheck`, `check_download(paths, nxdl)`, `download_and_promote(paths, nxdl, validate_client)`, `normalize_windows_backslash_names(staging)`.

- [ ] **Step 1: Write a failing verified-manifest test**

```python
binary = self.install_verified_nxdl()
with mock.patch("msclassic.client_download.subprocess.run", return_value=completed_json(17)) as run:
    result = check_download(self.paths, self.nxdl)
self.assertEqual(run.call_args.args[0], [str(binary), "tms_cw", "--check", "--json"])
self.assertEqual(result.total_size, 17)
```

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client_download -v`

Expected: module import failure.

- [ ] **Step 3: Implement verified nxdl check sharing existing updater policy**

```python
def check_download(paths, nxdl):
    _ensure_not_locked(paths)
    completed = subprocess.run([str(_verified_nxdl(paths, nxdl)), "tms_cw", "--check", "--json"], shell=False, env=_minimal_environment(paths), text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=120, check=False)
    total = parse_manifest_json(completed.stdout)
    available = shutil.disk_usage(paths.client.parent).free
    return DownloadCheck(total, available, available >= total + 1024**3, "ready")
```

Move updater validation/lock/environment helpers to this module and import them back into `updater.py`, retaining updater behavior.

- [ ] **Step 4: Verify green**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client_download tests.test_updater -v`

Expected: PASS.

- [ ] **Step 5: Write failing promotion-safety tests**

```python
with mock.patch("msclassic.client_download.subprocess.run", side_effect=write_windows_named_client):
    download_and_promote(self.paths, self.nxdl, validate_client)
self.assertTrue((self.paths.client / "Maplestory_Classic.exe").is_file())
with self.assertRaises(ClientDownloadError):
    normalize_windows_backslash_names(tree_with("..\\\\escape"))
```

- [ ] **Step 6: Verify red**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client_download -v`

Expected: missing promotion behavior.

- [ ] **Step 7: Implement staging, normalization, validation, and atomic promotion**

```python
with _exclusive_launch_lock(paths):
    stage = paths.client.with_name(".MapleStoryClassic.download")
    _run_nxdl_download(_verified_nxdl(paths, nxdl), paths, stage)
    normalize_windows_backslash_names(stage)
    _reject_unsafe_tree(stage)
    validate_client(stage)
    stage.replace(paths.client)
```

Use `lstat()`, split literal backslashes only in basenames, reject empty/dot/traversal/slash components and collisions, and do not remove staging in exception paths.

- [ ] **Step 8: Verify and commit**

Run: `PYTHONPATH=src python3 -m unittest tests.test_client_download tests.test_updater tests.test_paths_lockfile -v`

Expected: PASS.

Commit: `git add src/msclassic/client_download.py src/msclassic/updater.py tests/test_client_download.py tests/test_updater.py && git commit -m "feat: add verified client download staging"`

### Task 2: Installer and CLI integration

**Files:**

- Modify: `src/msclassic/installer.py`, `src/msclassic/cli.py`
- Modify: `tests/test_installer.py`, `tests/test_cli_integration.py`

**Interfaces:**

- Produces: `build_install_plan(..., source: Path | None, download_client: bool)` and `InstallAction("acquire_client")`.

- [ ] **Step 1: Write failing mode-contract tests**

```python
plan = build_install_plan(self.paths, self.artifacts, None, LUBUNTU_2404, download_client=True)
kinds = [action.kind for action in plan.actions]
self.assertLess(kinds.index("acquire_client"), kinds.index("initialize_prefix"))
code, out, _ = self.invoke(["install", "--dry-run", "--download-client"])
self.assertEqual(code, 0)
self.assertIn("zero mutations", out)
```

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=src python3 -m unittest tests.test_installer tests.test_cli_integration -v`

Expected: current source default fails the mode contract.

- [ ] **Step 3: Implement explicit modes**

```python
if download_client and not paths.client.exists():
    actions.append(InstallAction("acquire_client", destination=paths.client, artifact=artifacts["nxdl"]))
elif source is None:
    raise InstallerError("choose --source PATH or --download-client")
```

Run acquisition only after nxdl `install_binary`; preserve old source backup/import flow; map download errors to `InstallerError`; make `install` arguments mutually exclusive; retain source-oriented `plan`; ensure installer dry-run only prints actions.

- [ ] **Step 4: Verify and commit**

Run: `PYTHONPATH=src python3 -m unittest tests.test_installer tests.test_cli_integration -v`

Expected: PASS.

Commit: `git add src/msclassic/installer.py src/msclassic/cli.py tests/test_installer.py tests/test_cli_integration.py && git commit -m "feat: expose explicit client download installation"`

### Task 3: Wrapper, documentation, final verification

**Files:**

- Modify: `platforms/lubuntu-24.04/install.sh`, `tests/test_platforms.py`
- Modify: `README.md`, `docs/quick-start-lubuntu-pve.md`, `docs/troubleshooting.md`

- [ ] **Step 1: Write failing wrapper/docs tests**

```python
self.assertIn("acquire_client", run_wrapper("--dry-run", "--download-client").stdout)
self.assertEqual(run_wrapper("--dry-run").returncode, 2)
self.assertIn(".MapleStoryClassic.download", (REPO / "docs/quick-start-lubuntu-pve.md").read_text())
```

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=src python3 -m unittest tests.test_platforms -v`

Expected: wrapper/docs assertions fail.

- [ ] **Step 3: Implement wrapper mode forwarding and docs**

```bash
client_mode=()
case "$1" in --source) client_mode=(--source "$2"); shift 2 ;; --download-client) client_mode=(--download-client); shift ;; esac
[[ "${#client_mode[@]}" -gt 0 ]] || usage
```

Document public download, no stored credentials, free-space behavior, retained stage, invalid-final refusal, official login, manual updates, and the fresh-VM map/exit/relaunch acceptance gate.

- [ ] **Step 4: Verify, commit, and push**

Run: `bash scripts/test.sh && bash scripts/secret-scan.sh && git diff --check && bash platforms/lubuntu-24.04/install.sh --dry-run --download-client && bash platforms/lubuntu-24.04/install.sh --dry-run --source /media/ubuntu/MapleStoryClassic`

Expected: PASS; neither dry-run contacts nxdl nor creates a client.

Commit and push: `git add platforms/lubuntu-24.04/install.sh tests/test_platforms.py README.md docs/quick-start-lubuntu-pve.md docs/troubleshooting.md && git commit -m "docs: document first-time client download" && git push origin HEAD`
