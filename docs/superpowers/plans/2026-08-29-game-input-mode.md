# Game Input Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make the official MapleStory Classic launch temporarily suppress interfering Lubuntu desktop shortcuts while preserving Alt+Tab and the user's Fcitx chat toggle.

**Architecture:** A new input_mode module owns all Fcitx, Openbox, and LXQt configuration work. It snapshots user configuration in the project state directory, applies a narrow temporary profile, and restores it in a finally block after Wine exits. The authenticated launch path is the only automatic caller; msclassic input status and msclassic input restore provide observability and recovery.

**Tech Stack:** Python 3.12 standard library (configparser, xml.etree.ElementTree, json, subprocess); Fcitx 5; Openbox; LXQt global shortcuts; unittest.

**Spec:** docs/superpowers/specs/2026-08-29-game-input-mode-design.md

## Global Constraints

- Support only X11 with running Openbox and lxqt-globalkeysd; leave other desktops unchanged.
- Never edit /etc, Proxmox, the host, MapleStory files, Wine registry input settings, GRAP, or NGS.
- Keep Alt+Tab and Alt+Shift+Tab; remove every other configurable Openbox/LXQt desktop shortcut only while Wine is running.
- Preserve the user's Fcitx trigger (currently Left Shift); request inactive/direct input using only fcitx5-remote -c on a best-effort basis.
- Keep backups under ~/.local/state/maplestory-classic/input-profile/ with 0700 directory and 0600 files; write atomically and restore exact prior user files.
- Do not log or export authenticated launch arguments, account data, browser URIs, or session-bus addresses.
- Preserve the existing clean-shell subprocess.run call with shell=False launch policy.

---

### Task 1: Pure temporary-profile transformations

**Files:**

- Create: src/msclassic/input_mode.py
- Create: tests/test_input_mode.py

**Interfaces:**

- Produces InputModeError(ValueError) for local profile errors.
- Produces InputModeStatus(state: str, detail: str) with to_json() -> dict[str, str].
- Produces _transform_openbox(source: bytes) -> bytes and _transform_lxqt(source: bytes) -> bytes.
- Produces _desktop_paths(paths: AppPaths, environment: Mapping[str, str]) -> DesktopPaths.

- [ ] **Step 1: Write the failing Openbox transformation test**

~~~
def test_openbox_profile_keeps_only_alt_tab_bindings(self):
    transformed = _transform_openbox(OPENBOX_SAMPLE)
    self.assertIn(b'key="A-Tab"', transformed)
    self.assertIn(b'key="A-S-Tab"', transformed)
    self.assertNotIn(b'key="A-space"', transformed)
    self.assertNotIn(b'key="A-F4"', transformed)
    self.assertNotIn(b'key="W-d"', transformed)
~~~

- [ ] **Step 2: Run it to verify it fails**

Run: python3 -m unittest tests.test_input_mode.InputModeTransformTests.test_openbox_profile_keeps_only_alt_tab_bindings -v

Expected: FAIL because msclassic.input_mode does not exist.

- [ ] **Step 3: Implement the minimal Openbox transform**

~~~
def _transform_openbox(source: bytes) -> bytes:
    root = ElementTree.fromstring(source)
    keyboard = next(node for node in root.iter() if _local_name(node.tag) == "keyboard")
    for binding in list(keyboard):
        if _local_name(binding.tag) == "keybind" and binding.get("key") not in {"A-Tab", "A-S-Tab"}:
            keyboard.remove(binding)
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
~~~

Use _local_name so namespaced and unnamespaced XML both work. Raise InputModeError("Openbox keyboard configuration is malformed") if no keyboard section exists.

- [ ] **Step 4: Run the Openbox test to verify it passes**

Run: python3 -m unittest tests.test_input_mode.InputModeTransformTests.test_openbox_profile_keeps_only_alt_tab_bindings -v

Expected: PASS.

- [ ] **Step 5: Write the failing LXQt transformation test**

~~~
def test_lxqt_profile_disables_desktop_keys_and_keeps_hardware_keys(self):
    transformed = _transform_lxqt(LXQT_SAMPLE).decode("utf-8")
    self.assertIn("[Alt%2BSpace.1]\nEnabled=false", transformed)
    self.assertIn("[Meta%2BD.2]\nEnabled=false", transformed)
    self.assertIn("[Print.3]\nEnabled=false", transformed)
    self.assertIn("[XF86AudioMute.4]\nEnabled=true", transformed)
~~~

- [ ] **Step 6: Run it to verify it fails**

Run: python3 -m unittest tests.test_input_mode.InputModeTransformTests.test_lxqt_profile_disables_desktop_keys_and_keeps_hardware_keys -v

Expected: FAIL because _transform_lxqt does not exist.

- [ ] **Step 7: Implement the minimal LXQt transform**

~~~
def _transform_lxqt(source: bytes) -> bytes:
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(source.decode("utf-8"))
    for section in parser.sections():
        if section != "General" and not section.startswith("XF86"):
            parser.set(section, "Enabled", "false")
    stream = io.StringIO()
    parser.write(stream, space_around_delimiters=False)
    return stream.getvalue().encode("utf-8")
~~~

Wrap decoding and parsing failures in InputModeError("LXQt shortcut configuration is malformed"). Preserve non-shortcut options and all XF86 hardware bindings unchanged.

- [ ] **Step 8: Run the transformation test class**

Run: python3 -m unittest tests.test_input_mode.InputModeTransformTests -v

Expected: PASS.

- [ ] **Step 9: Commit**

~~~
git add src/msclassic/input_mode.py tests/test_input_mode.py
git commit -m "feat: add game input profile transforms"
~~~

### Task 2: Transactional activation, restore, and Fcitx preparation

**Files:**

- Modify: src/msclassic/input_mode.py
- Modify: tests/test_input_mode.py

**Interfaces:**

- Consumes the transformations and status type from Task 1.
- Produces deactivate_fcitx(environment: Mapping[str, str]) -> InputModeStatus.
- Produces activate_game_input(paths: AppPaths, environment: Mapping[str, str]) -> InputModeStatus.
- Produces restore_game_input(paths: AppPaths, environment: Mapping[str, str]) -> InputModeStatus.
- Produces game_input_status(paths: AppPaths, environment: Mapping[str, str]) -> InputModeStatus.

- [ ] **Step 1: Write failing lifecycle tests**

~~~
def test_deactivate_fcitx_uses_fixed_argv_and_is_nonfatal(self):
    with mock.patch("msclassic.input_mode.shutil.which", return_value="/usr/bin/fcitx5-remote"), \
         mock.patch("msclassic.input_mode.subprocess.run", return_value=CompletedProcess([], 0)) as run:
        result = deactivate_fcitx({"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"})
    self.assertEqual(result.state, "prepared")
    run.assert_called_once_with(
        ["/usr/bin/fcitx5-remote", "-c"],
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

def test_activate_then_restore_returns_exact_prior_files(self):
    before_openbox = self.openbox.read_bytes()
    before_lxqt = self.lxqt.read_bytes()
    self._supported_session()
    self.assertEqual(activate_game_input(self.paths, self.environment).state, "active")
    self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")
    self.assertEqual(self.openbox.read_bytes(), before_openbox)
    self.assertEqual(self.lxqt.read_bytes(), before_lxqt)
~~~

The fixture supplies a temporary XDG configuration root, sample Openbox/LXQt files, and mocks fixed-argv calls for pgrep, openbox --reconfigure, and systemctl --user restart app-lxqt\x2dglobalkeyshortcuts@autostart.service.

- [ ] **Step 2: Run the lifecycle tests to verify they fail**

Run: python3 -m unittest tests.test_input_mode.InputModeLifecycleTests -v

Expected: FAIL because lifecycle functions do not exist.

- [ ] **Step 3: Implement exact transaction storage and fixed-command session checks**

~~~
def activate_game_input(paths, environment):
    if not _session_supported(environment):
        return InputModeStatus("unavailable", "Lubuntu X11 input profile is unavailable")
    restore_game_input(paths, environment)
    backups = _capture_backups(_desktop_paths(paths, environment))
    _write_transaction(backups)
    try:
        _write_profile_files(backups)
        _reload_desktop(environment)
    except InputModeError:
        _restore_backups(backups)
        _reload_desktop(environment, allow_failure=True)
        raise
    return InputModeStatus("active", "temporary game input profile is active")
~~~

Capture raw file bytes and an existed flag in active.json; store bytes as base64 and write state with same-directory temporary files plus os.replace. Require XDG_SESSION_TYPE == "x11", DISPLAY, XDG_RUNTIME_DIR, openbox, and lxqt-globalkeysd. All external calls use fixed argument vectors and shell=False.

- [ ] **Step 4: Run lifecycle tests to verify they pass**

Run: python3 -m unittest tests.test_input_mode.InputModeLifecycleTests -v

Expected: PASS.

- [ ] **Step 5: Add and run failure-path tests**

~~~
def test_unsupported_session_leaves_configuration_unchanged(self):
    before = self.openbox.read_bytes(), self.lxqt.read_bytes()
    status = activate_game_input(self.paths, {**self.environment, "XDG_SESSION_TYPE": "wayland"})
    self.assertEqual(status.state, "unavailable")
    self.assertEqual((self.openbox.read_bytes(), self.lxqt.read_bytes()), before)

def test_activation_reload_failure_restores_both_files(self):
    before = self.openbox.read_bytes(), self.lxqt.read_bytes()
    self._command_failure("openbox", "--reconfigure")
    with self.assertRaises(InputModeError):
        activate_game_input(self.paths, self.environment)
    self.assertEqual((self.openbox.read_bytes(), self.lxqt.read_bytes()), before)

def test_restore_is_idempotent(self):
    self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")
    self.assertEqual(restore_game_input(self.paths, self.environment).state, "inactive")

def test_stale_transaction_is_restored_before_a_new_activation(self):
    self.assertEqual(activate_game_input(self.paths, self.environment).state, "active")
    self.assertEqual(activate_game_input(self.paths, self.environment).state, "active")

def test_restore_removes_generated_files_when_no_prior_user_files_existed(self):
    self.openbox.unlink()
    self.lxqt.unlink()
    activate_game_input(self.paths, self.environment)
    restore_game_input(self.paths, self.environment)
    self.assertFalse(self.openbox.exists())
    self.assertFalse(self.lxqt.exists())

def test_fcitx_missing_or_nonzero_result_does_not_raise(self):
    with mock.patch("msclassic.input_mode.shutil.which", return_value=None):
        self.assertEqual(deactivate_fcitx(self.environment).state, "unavailable")
~~~

Run: python3 -m unittest tests.test_input_mode -v

Expected: PASS, including rollback and stale-transaction cases.

- [ ] **Step 6: Commit**

~~~
git add src/msclassic/input_mode.py tests/test_input_mode.py
git commit -m "feat: add reversible game input profile"
~~~

### Task 3: Integrate the official launcher and recovery CLI

**Files:**

- Modify: src/msclassic/runner.py
- Modify: src/msclassic/cli.py
- Modify: tests/test_runner.py
- Modify: tests/test_cli_integration.py

**Interfaces:**

- Consumes the Task 2 functions.
- Produces msclassic input status and msclassic input restore.
- Produces an authenticated launcher that restores the profile after Wine exits or fails to spawn.

- [ ] **Step 1: Write failing runner-ordering tests**

~~~
def test_authenticated_launch_prepares_input_and_restores_after_wine(self):
    events = []
    with mock.patch("msclassic.runner.deactivate_fcitx", side_effect=lambda *_: events.append("fcitx")), \
         mock.patch("msclassic.runner.activate_game_input", side_effect=lambda *_: events.append("activate") or ACTIVE), \
         mock.patch("msclassic.runner.subprocess.run", side_effect=lambda *_a, **_kw: events.append("wine") or CompletedProcess([], 0)), \
         mock.patch("msclassic.runner.restore_game_input", side_effect=lambda *_: events.append("restore")):
        run_authenticated(self.request, self.paths)
    self.assertEqual(events, ["fcitx", "activate", "wine", "restore"])
~~~

Add a second test where Wine raises OSError and assert restore is called. Add XDG_CONFIG_HOME and XDG_SESSION_TYPE to the allowed launch environment fixture.

- [ ] **Step 2: Run runner-ordering tests to verify they fail**

Run: python3 -m unittest tests.test_runner.RunnerTests.test_authenticated_launch_prepares_input_and_restores_after_wine -v

Expected: FAIL because runner integration is absent.

- [ ] **Step 3: Implement launcher cleanup without changing launch privacy**

~~~
deactivate_fcitx(environment)
profile = activate_game_input(paths, environment)
try:
completed = subprocess.run(
    list(argv), shell=False, env=environment,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, start_new_session=True, check=False,
)
finally:
    if profile.state == "active":
        restore_game_input(paths, environment)
~~~

Treat InputModeError as profile-unavailable after its own rollback and continue the game launch. Do not include URI arguments or Fcitx output in last-launch-status.json.

- [ ] **Step 4: Run runner tests**

Run: python3 -m unittest tests.test_runner -v

Expected: PASS.

- [ ] **Step 5: Write failing CLI tests**

~~~
def test_input_status_prints_safe_json(self):
    with mock.patch("msclassic.cli.game_input_status", return_value=InputModeStatus("inactive", "normal")):
        stdout = self._run_cli(["input", "status"])
    self.assertEqual(json.loads(stdout), {"detail": "normal", "state": "inactive"})

def test_input_restore_delegates_to_profile_manager(self):
    with mock.patch("msclassic.cli.restore_game_input", return_value=InputModeStatus("inactive", "restored")) as restore:
        self.assertEqual(main(["input", "restore"]), 0)
    restore.assert_called_once()
~~~

- [ ] **Step 6: Run CLI tests to verify they fail**

Run: python3 -m unittest tests.test_cli_integration -v

Expected: FAIL because input is not an accepted command.

- [ ] **Step 7: Add parser and dispatch**

~~~
input_command = subcommands.add_parser("input")
input_subcommands = input_command.add_subparsers(dest="input_command", required=True)
input_subcommands.add_parser("status")
input_subcommands.add_parser("restore")
~~~

Dispatch status with sorted JSON from InputModeStatus.to_json(). Dispatch restore without confirmation because it only returns the desktop to its pre-game state. Convert InputModeError to the existing configuration exit code.

- [ ] **Step 8: Run integration tests**

Run: python3 -m unittest tests.test_cli_integration tests.test_runner -v

Expected: PASS.

- [ ] **Step 9: Commit**

~~~
git add src/msclassic/runner.py src/msclassic/cli.py tests/test_runner.py tests/test_cli_integration.py
git commit -m "feat: apply game input mode on launch"
~~~

### Task 4: Document, verify, and run the VM acceptance trial

**Files:**

- Modify: README.md
- Modify: docs/quick-start-lubuntu-pve.md
- Modify: docs/troubleshooting.md
- Modify: docs/architecture.md
- Modify: docs/superpowers/plans/2026-08-29-game-input-mode.md
- Modify: tests/test_platforms.py

**Interfaces:**

- Consumes automatic launcher behavior and msclassic input status|restore from Task 3.
- Produces reproducible Game input mode documentation and a checked-off implementation plan.

- [ ] **Step 1: Write a failing documentation test**

~~~
def test_docs_describe_game_input_mode_and_restore(self):
    text = (REPO / "docs/quick-start-lubuntu-pve.md").read_text(encoding="utf-8")
    self.assertIn("msclassic input status", text)
    self.assertIn("msclassic input restore", text)
    self.assertIn("Alt+Tab", text)
~~~

- [ ] **Step 2: Run it to verify it fails**

Run: python3 -m unittest tests.test_platforms -v

Expected: FAIL because Game input mode is undocumented.

- [ ] **Step 3: Document exact workflow and limits**

Document direct-input start; Left Shift as the current Fcitx trigger for Chinese chat; the need to return to English before action keys; preserved Alt+Tab/Alt+Shift+Tab; RustDesk exclusion from held-key validation; and msclassic input restore for a crash-interrupted profile. State that no Proxmox or system configuration changes occur and that this feature is Lubuntu/Openbox/LXQt-specific.

- [ ] **Step 4: Run documentation tests**

Run: python3 -m unittest tests.test_platforms -v

Expected: PASS.

- [ ] **Step 5: Run all automated checks and secret scan**

Run: bash scripts/test.sh && bash scripts/secret-scan.sh

Expected: all tests pass and the scan reports no secrets.

- [ ] **Step 6: Close the running dedicated game session and run the manual VM trial**

Run: ~/.local/bin/msclassic stop --yes

Confirm the dedicated Wine game and grap-core64.aes processes exited. Launch normally from Chromium/GamePass, then use noVNC and AnyDesk for every manual acceptance check in the spec. Record only non-sensitive observations with msclassic trial; never include login data or launch URIs.

- [ ] **Step 7: Mark plan tasks completed, commit, and push**

~~~
git add README.md docs tests docs/superpowers/plans/2026-08-29-game-input-mode.md
git commit -m "docs: document game input mode"
git push
~~~
