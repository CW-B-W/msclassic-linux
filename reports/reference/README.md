# Reference evidence

This directory is reserved for reviewed, non-sensitive reference fingerprints and reports. The first VM has passed live gameplay, Chinese input, and the scoped Windows-debugger compatibility trial. It has not yet passed clean-boot/relaunch and multi-VM acceptance, so no platform fingerprint is promoted here yet.

A candidate can be promoted only after:

- official-site launch on a clean boot without manually running doctor;
- character selection, map entry, and at least 15 minutes of gameplay;
- normal exit and a second website launch;
- review with `scripts/secret-scan.sh`;
- exact runtime/profile provenance; and
- the intended concurrency test when making a multi-VM claim.

Never commit authenticated URLs, launch arguments, credentials, cookies, browser profiles, game files, Wine prefixes, or raw command lines containing private values.
