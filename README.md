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

Devices fetch over `raw.githubusercontent.com` (no clone). Intended interface:
**Reel CLI** — `reel catalog publish` (new pin, usually `dev`) and
`reel catalog promote` (move `staging` / `stable` to an existing release;
pointer only — no rebuild). Engines live in [`scripts/publish.py`](scripts/publish.py)
and [`scripts/promote.py`](scripts/promote.py) until the CLI wraps them.

## Site lifecycle (feature → field)

**Review doc:** [`SDLC.md`](SDLC.md) — full propagation, promotion, cinema-card
worked example, hotfix, and rollback (no long-lived stage/prod/hotfix git
branches).

In short: git `main` feeds catalog **`dev`**; production is catalog
**`stable`** plus site Infisical env=`stable`. One lab `site_id` walks
`dev → staging → stable`; field sites enroll on an armed `stable` release.

```text
L0 Vite + dev site → L1 main/CI pin on VM → L2 promote+site to staging
  → L3 promote+site to stable → arm → field
```

Staging/stable move only via `reel catalog promote` (engine:
[`scripts/promote.py`](scripts/promote.py)). File contracts: [`SCHEMA.md`](SCHEMA.md).
