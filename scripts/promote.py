#!/usr/bin/env python3
"""
promote.py — move a channel pointer to an existing immutable release.

Does not rebuild images or write a new release tree. Used after a pin on
`dev` (or another source channel) has been soak-tested, to advance
`staging` then `stable` to that same release id.

Invoked by a product CI workflow_dispatch (or manually) that has checked
out the catalog repo:

  # Promote whatever currently tips cinema/dev → cinema/staging
  python3 scripts/promote.py \\
    --catalog-root . \\
    --product reel-edge --variant cinema \\
    --from-channel dev --to-channel staging

  # Promote an explicit release id → cinema/stable
  python3 scripts/promote.py \\
    --catalog-root . \\
    --product reel-edge --variant cinema \\
    --release-id 2026-10-22T2038Z --to-channel stable

Exactly one of --from-channel / --release-id is required.
Prints the promoted release id on stdout.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ID_RE = re.compile(r"^[0-9A-Za-z._:\-]+$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Promote targets are the soak / production tracks. `dev` and `nightly` are
# written by publish.py (CI Build / CI Nightly), not by promote.
PROMOTE_TO = frozenset({"staging", "stable"})


def die(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    raise SystemExit(1)


def parse_channel_release(path: Path) -> str | None:
    """Return the release id from a channel pointer, or None if unset/placeholder.

    Ignores blank lines and `#` comments (placeholder stamps).
    """
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not ID_RE.match(line):
            die(f"invalid release id in {path}: {line!r}")
        return line
    return None


def require_channel_release(path: Path, label: str) -> str:
    rid = parse_channel_release(path)
    if rid is None:
        die(f"{label}: no release id in {path} (missing, empty, or comment-only)")
    return rid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog-root", default=".")
    ap.add_argument("--product", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--to-channel", required=True, help="staging or stable")
    ap.add_argument(
        "--from-channel",
        default="",
        help="Read release id from this channel pointer (e.g. dev)",
    )
    ap.add_argument(
        "--release-id",
        default="",
        help="Explicit release id under products/<product>/releases/<variant>/",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for name, val in (("product", args.product), ("variant", args.variant), ("to-channel", args.to_channel)):
        if not SLUG_RE.match(val):
            die(f"{name} must be lower-kebab-case: {val!r}")
    if args.to_channel not in PROMOTE_TO:
        die(f"to-channel must be one of {sorted(PROMOTE_TO)}: {args.to_channel!r}")

    from_ch = (args.from_channel or "").strip()
    release_id = (args.release_id or "").strip()
    if bool(from_ch) == bool(release_id):
        die("provide exactly one of --from-channel or --release-id")
    if from_ch and not SLUG_RE.match(from_ch):
        die(f"from-channel must be lower-kebab-case: {from_ch!r}")
    if from_ch == args.to_channel:
        die("from-channel and to-channel must differ")

    root = Path(args.catalog_root)
    chan_dir = root / "products" / args.product / "channels" / args.variant
    rel_root = root / "products" / args.product / "releases" / args.variant
    to_file = chan_dir / f"{args.to_channel}.txt"

    if from_ch:
        release_id = require_channel_release(chan_dir / f"{from_ch}.txt", "from-channel")
    elif not ID_RE.match(release_id):
        die(f"invalid release id: {release_id!r}")

    rel_dir = rel_root / release_id
    if not (rel_dir / "release.json").is_file():
        die(f"release does not exist (need publish first): {rel_dir}")

    prev = parse_channel_release(to_file) or ""

    if prev == release_id:
        print(
            f"::notice::{args.product}/{args.variant}/{args.to_channel} "
            f"already at {release_id}",
            file=sys.stderr,
        )
        print(release_id)
        return 0

    if args.dry_run:
        src = f"from {from_ch}" if from_ch else "explicit"
        print(
            f"DRY-RUN would point {to_file} -> {release_id} ({src}; was {prev or 'unset'})",
            file=sys.stderr,
        )
        print(release_id)
        return 0

    to_file.parent.mkdir(parents=True, exist_ok=True)
    to_file.write_text(release_id + "\n", encoding="utf-8")
    print(
        f"::notice::promoted {args.product}/{args.variant}: "
        f"{args.to_channel} {prev or 'unset'} -> {release_id}",
        file=sys.stderr,
    )
    print(release_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
