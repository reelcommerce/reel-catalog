# reel-catalog schema

Every file is public and free of secrets. Releases are immutable; only channel
pointers move.

## Channel pointer — `products/<product>/channels/<variant>/<channel>.txt`

Single line, the release id it currently points at:

```text
2026-07-17T0815Z
```

## Release metadata — `.../releases/<variant>/<release-id>/release.json`

```json
{
  "product": "reel-builder",
  "variant": "builder",
  "release": "2026-07-17T0815Z",
  "created_utc": "2026-07-17T08:15:03Z",
  "source": {
    "repo": "reelcommerce/reel-builder",
    "sha": "aa13df2",
    "workflow": "ci-release",
    "run_id": "123456789"
  },
  "architectures": {
    "arm64": { "env": "manifest.arm64.env" },
    "amd64": { "env": "manifest.amd64.env" }
  }
}
```

Each architecture entry references one or both artifact kinds:

- `"env": "manifest.<arch>.env"` — docker image pins (reel-docker, reel-builder).
- `"image": "image.<arch>.json"` — a flashable OS image (reel-os).

`arm64` is the default fleet arch for cinema/builder OS stations. `amd64` is
the real arch for `reel-edge` (app_image). Clients that request a missing
arch fall back to `arm64` when present.

## Arch manifest — `.../manifest.<arch>.env`

Compose `--env-file` friendly. Each line is `KEY=repo@sha256:<digest>`:

```dotenv
# reel-builder / builder / arm64
BUILDER_SERVICE_IMAGE=reelcommerce/builder-service@sha256:<64hex>
DASHBOARD_SERVICE_IMAGE=reelcommerce/dashboard-service@sha256:<64hex>
DASHBOARD_UI_IMAGE=reelcommerce/dashboard-ui@sha256:<64hex>
```

Validation (enforced by `publish.py` and device `reel-release.sh`):

- every non-comment line matches `^[A-Z0-9_]+=.+@sha256:[a-f0-9]{64}$`
- at least one `*_IMAGE=` entry
- no secret-looking tokens

## OS-image manifest — `.../image.<arch>.json`

Describes a flashable OS image (product `reel-os`, `variant = <site-id>`). The
binary itself lives as a GitHub Release asset in `reelcommerce/reel-os`; the
catalog only records a pinned pointer to it:

```json
{
  "filename": "reel-os-site-beckenham-london-uk-20260717-1200.img.gz",
  "sha256": "<64hex>",
  "url": "https://github.com/reelcommerce/reel-os/releases/download/<tag>/<filename>",
  "bytes": 123456789,
  "tag": "site-beckenham-london-uk-20260717-1200"
}
```

Validation (enforced by `publish.py`):

- `filename` non-empty
- `sha256` matches `^[a-f0-9]{64}$`
- `url` begins with `https://`
- no secret-looking tokens

## Promote — `scripts/promote.py`

Moves an existing channel pointer to an existing release id. Does **not**
create a new release directory or rebuild images.

```bash
python3 scripts/promote.py \
  --catalog-root . \
  --product <product> --variant <variant> \
  --to-channel staging|stable \
  (--from-channel <channel> | --release-id <id>) \
  [--dry-run]
```

Rules:

- `--to-channel` must be `staging` or `stable` (CI Build owns `dev`; nightly owns `nightly`).
- Exactly one of `--from-channel` / `--release-id`.
- Target release must already exist under `products/<product>/releases/<variant>/<id>/`.
- Channel files may be comment-only placeholders; promote overwrites them with a single release-id line.
- Idempotent: if the target channel already points at the release id, exit 0.

Site binding (outside this repo): a lab/canary site keeps one `site_id`, stores
`channel` + Infisical env tag, and flips both when the pack is promoted. Real
cinema sites stay on `channel=stable` and only reconcile after `stable` moves.
