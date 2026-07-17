# reel-catalog

Public, immutable, digest-pinned release catalog for all Reel products.

Supersedes `reel-releases`. Runtime clients resolve a release from three values:

```text
PRODUCT   e.g. reel-os
VARIANT   e.g. cinema | builder | gateway | runner
CHANNEL   e.g. stable | latest | beta | nightly
```

## Hierarchy

```text
Product → Variant → Channel → Release → Architecture → Manifest
```

## Layout

```text
products/
  <product>/
    channels/
      <variant>/
        <channel>.txt          # single line: release id
    releases/
      <variant>/
        <release-id>/          # e.g. 2026-07-17T0815Z
          release.json         # metadata + arch index
          manifest.arm64.env   # KEY=repo@sha256 pins (compose --env-file friendly)
          manifest.amd64.env   # optional; arch stub allowed
          notes.md
```

## Resolution

```text
products/<product>/channels/<variant>/<channel>.txt
        ↓ release id
products/<product>/releases/<variant>/<release-id>/release.json
        ↓ architectures.<arch>.env
products/<product>/releases/<variant>/<release-id>/manifest.<arch>.env
```

Devices fetch over `raw.githubusercontent.com` (no clone). CI publishes with
[`scripts/publish.py`](scripts/publish.py).

See [`SCHEMA.md`](SCHEMA.md) for the exact file contracts.
