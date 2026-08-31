# Development workflow

`main` contains the supported implementation, regression tests and current
setup/reference documentation. Keep commits focused on completed changes.

Do experimental work on a `codex/` branch. Keep raw traces, credentials,
authenticated URLs, downloaded binaries, prefixes and personal browser data
out of Git. Existing research history remains on the development branches;
do not merge that history or investigation diaries into `main`.

Before integration:

1. Add a regression test for the changed behavior.
2. Run `bash scripts/test.sh` and `bash scripts/secret-scan.sh`.
3. Check installer dry-run, runtime hashes and applicable live acceptance.
4. Review the diff and update the current user documentation.
5. Squash a finished change into a concise commit on `main`; retain the
   development branch when its audit history is useful.

No automated test is a substitute for a live gameplay/input acceptance run.
No project script may change Proxmox settings. Ask the operator to perform
necessary host work through Proxmox WebUI.
