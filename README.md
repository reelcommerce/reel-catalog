# reel-catalog

Public, immutable, digest-pinned release catalog for all Reel products.

Supersedes `reel-releases`. Runtime clients resolve a release from three values:

```text
PRODUCT   the publishing project — reel-docker | reel-builder | reel-edge | reel-node
VARIANT   the station flavour     — cinema | builder | edge | node | ads | pos
CHANNEL   the release track        — dev | staging | stable | nightly
```

The catalog tracks **container image pins** (compose `--env-file` friendly),
resolved at first boot by the station's docker stack:

| Product        | Variant  | Published by            | Consumed by            |
| -------------- | -------- | ----------------------- | ---------------------- |
| `reel-docker`  | `cinema` | reel-docker CI          | cinema-rpi station     |
| `reel-builder` | `builder`| reel-builder CI         | builder-rpi station    |
| `reel-edge`    | `cinema` / `ads` / `pos` | reel-edge CI (amd64) | site VM web pack (`edge` leftover) |
| `reel-node`    | `node`   | reel-node CI (arm64) + Reel Node OS bake | chain board (Besu via `BESU_IMAGE`) |

Infisical (later bind): `/products/reel-edge/fleet` and `/products/reel-edge/sites/{site_id}` — same product id as this catalog. Lab/canary sites keep one `site_id` and flip an env tag (`dev` → `staging` → `stable`) when promoted; real cinema sites stay on `stable` only.

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

Devices fetch over `raw.githubusercontent.com` (no clone). CI **publishes** new
pins with [`scripts/publish.py`](scripts/publish.py). After soak-test, CI
**promotes** an existing release to `staging` / `stable` with
[`scripts/promote.py`](scripts/promote.py) (channel pointer only — no rebuild).

## Promotion (lab/canary site up the chain)

Channels are not git branches. Routine `CI Build` stamps **`dev`** only.
Promotion is an explicit human-triggered step after the pack has been tested
on a lab site enrolled on that channel:

```text
feature → merge → CI Build → channel=dev
        → install pack on lab site (channel=dev), Infisical env=dev
        → test OK
        → promote.py --from-channel dev --to-channel staging
        → flip lab site channel + Infisical env → staging, re-Save / reconcile
        → integration / UAT OK
        → promote.py --from-channel staging --to-channel stable
        → flip lab site → stable (optional) OR leave lab on staging
        → production cinema sites (always channel=stable) pull the new pin
```

Do **not** enroll a second stage VM for the lab path: one `site_id` walks
`dev → staging → stable` with the pack. Production cinema sites never start
on `dev`; they only consume `stable` pin moves.

Example (cinema web pack):

```bash
python3 scripts/promote.py \
  --catalog-root . \
  --product reel-edge --variant cinema \
  --from-channel dev --to-channel staging

python3 scripts/promote.py \
  --catalog-root . \
  --product reel-edge --variant cinema \
  --from-channel staging --to-channel stable
```

See [`SCHEMA.md`](SCHEMA.md) for the exact file contracts.
