# Zero-Client Download Design

## Goal

Allow a fresh, supported Lubuntu 24.04 / Proxmox VirGL VM to obtain the
MapleStory Classic client without a mounted client ISO, while retaining the
existing verified `--source` installation path and the project's privacy,
integrity, and no-bypass constraints.

## Scope and non-goals

The feature adds one explicit initial-install mode:

```bash
bash platforms/lubuntu-24.04/install.sh --download-client
```

It uses the already locked and checksum-verified Linux `nxdl` binary with the
Classic alias `tms_cw`. It downloads game content only from the manifest that
`nxdl` resolves. It does not distribute game files, automate Beanfun login,
store credentials, manufacture launch arguments, change Proxmox, or alter
GRAP/NGS-X.

The existing source-import command remains supported and unchanged in intent:

```bash
bash platforms/lubuntu-24.04/install.sh \
  --source /media/ubuntu/MapleStoryClassic
```

The mode arguments are mutually exclusive. Exactly one is required for a real
installation. A dry run accepts either mode but does not access the network or
create a client directory.

This version does not add a graphical downloader, automatic updates, a
credential flow, a forced overwrite option, or a cleanup command for an
interrupted staging download.

## Existing evidence and design basis

The current project already pins `nxdl` and invokes:

```text
nxdl tms_cw --check --json
nxdl tms_cw --download <client directory>
```

for explicit updates. CitrusGate documents the same Classic alias and an
initial-client download flow. Its macOS implementation also normalizes files
whose basenames contain Windows backslashes after a download. The current
Linux feature must make that normalization defensive and independent of
whether the pinned Linux release currently exhibits the behavior.

The existing installer validates a client tree before any Wine prefix work.
The new flow preserves that ordering: only a validated downloaded tree can
become the client consumed by the Wine/NGS bootstrap.

## Operator interface

`platforms/lubuntu-24.04/install.sh` gains `--download-client` and no longer
silently supplies a source directory when neither mode was selected. It keeps
`--dry-run` and `--platform` behavior.

The Python CLI gains matching mutually exclusive `install --source PATH` and
`install --download-client` inputs. The standalone plan command remains
source-oriented in this iteration; initial download planning is performed by
`install --dry-run --download-client` and reports that manifest size is only
available during the real, verified acquisition step.

The user sees `nxdl`'s native terminal output during a real initial download.
The implementation does not parse an unstable progress format or emit an
authenticated value. `nxdl` receives only the game alias and a local staging
path.

## Data flow

```text
operator selects --download-client
  -> package bootstrap and normal X11/VirGL gate
  -> download and SHA-256 verify locked Wine and nxdl artifacts
  -> nxdl tms_cw --check --json
  -> require manifest total_size + 1 GiB available at ~/Games
  -> nxdl tms_cw --download ~/Games/.MapleStoryClassic.download
  -> normalize safe Windows-backslash filename artifacts in staging
  -> validate required Classic and GRAP/NGS files; reject links/special files
  -> atomically rename staging to ~/Games/MapleStoryClassic
  -> existing prefix initialization, registry import, NGS installation,
     desktop-handler registration, and website launch flow
```

`~/Games/.MapleStoryClassic.download` is always a sibling of the final client
directory, so promotion is an atomic same-filesystem rename. The live client
path is never partially populated. The staging directory is not used by the
game or runner.

If the final client already validates, the installer reuses it and does not
download again. If it exists but is invalid, installation stops without
overwriting it. If staging remains after an interrupted download, retrying the
same explicit mode reuses that staging directory; no automatic deletion occurs.

## Integrity and safety rules

- The locked `nxdl` binary must pass the existing checksum and executable
  verification before either manifest query or download.
- `--check --json` must remain bounded to one valid JSON object and the parsed
  `total_size` must remain within the existing maximum.
- The destination filesystem must have at least `total_size + 1 GiB` free
  before starting game acquisition, in addition to the installer's established
  runtime/build-headroom gate.
- Download is refused if a game launch or update owns the existing mode-0600
  lock.
- Staging and final client paths must resolve underneath the configured Games
  directory. Existing links, special files, escaping path segments, and
  filename-normalization collisions are hard failures.
- The normalizer may split only a basename containing literal `\\` into
  nonempty relative path components. It rejects `.`, `..`, slash-containing
  components, symlinks, and any destination that already exists. It never
  follows a link or writes outside staging.
- Required-file validation runs after normalization and again after promotion.
- All subprocesses use argument vectors, a minimal environment, no shell, and
  no logging of game authentication values.

## Failure behavior and recovery

- A failed manifest query, invalid manifest size, insufficient disk, missing
  downloader, nonzero download exit, unsafe path, or incomplete client leaves
  the final client untouched.
- A failed download leaves staging in place for inspection or a later retry.
  The error identifies the stage generically but does not expose command output
  that could contain sensitive or unstable downloader data.
- An existing invalid final client is intentionally not renamed, deleted, or
  replaced. The operator can preserve it or move it aside after reviewing it.
- No Wine prefix or NGS installation action occurs until the downloaded tree
  has passed client validation.

## Test strategy

Unit tests will cover:

1. Mutually exclusive source/download client arguments and unchanged
   source-import behavior.
2. Zero-mutation dry-run behavior for the new mode.
3. The exact `nxdl --check --json` and `nxdl --download <stage>` argument
   vectors, verified binary requirement, lock refusal, disk gate, and exit
   handling.
4. Safe path normalization, no-op normalization, collisions, absolute or
   traversal components, and symlink rejection.
5. Atomic promotion only after complete client validation; valid final-client
   reuse; invalid final-client refusal; staging retention after failure.
6. Ordering that prevents prefix/NGS actions before validated client promotion.
7. Documentation references, with a manual acceptance checklist for the first
   fresh-VM download and live website launch.

## Acceptance criteria

On a fresh supported VM with no `~/Games/MapleStoryClassic` directory, the
operator can run the one explicit download-install command, observe `nxdl`
download the public Classic client, complete Wine/NGS installation, authenticate
only on the official Beanfun page, enter a live map, exit, and relaunch. The
result must be recorded as a second-VM acceptance run before the feature is
declared proven beyond the original VM.
