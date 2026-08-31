# Reference evidence

This directory is reserved for reviewed, non-sensitive platform fingerprints
and acceptance reports. See [validation status](../../docs/validation.md) for
current coverage. Raw trial output belongs outside the repository.

A candidate can be promoted only after:

- official-site launch on a clean boot without manually running doctor;
- character selection, map entry, and at least 15 minutes of gameplay;
- normal exit and a second website launch;
- review with `scripts/secret-scan.sh`;
- exact runtime/profile provenance; and
- the intended concurrency test when making a multi-VM claim.

Never commit authenticated URLs, launch arguments, credentials, cookies, browser profiles, game files, Wine prefixes, or raw command lines containing private values.
