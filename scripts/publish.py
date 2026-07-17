#!/usr/bin/env python3
"""
publish.py — write an immutable release into reel-catalog and move a channel.

Invoked by product CIs (reel-docker, reel-builder) that have checked out the
catalog repo. Given one or more arch pin files, it writes:

    products/<product>/releases/<variant>/<release-id>/
        release.json
        manifest.<arch>.env      (one per --arch <arch>=<path>)
        notes.md
    products/<product>/channels/<variant>/<channel>.txt   (-> release-id)

Usage:
  python3 scripts/publish.py \\
    --catalog-root . \\
    --product reel-os --variant builder --channel stable \\
    --arch arm64=release_out/manifest.arm64.env \\
    [--arch amd64=release_out/manifest.amd64.env] \\
    --source-repo reelcommerce/reel-builder --source-sha "$GIT_SHA" \\
    --workflow ci-release --run-id "$RUN_ID" \\
    [--release-id 2026-07-17T0815Z] [--notes "text"] [--dry-run]

Prints the release id on stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PIN_RE = re.compile(r"^[A-Z0-9_]+=.+@sha256:[a-f0-9]{64}$")
SECRET_RE = re.compile(r"(AKIA|ASIA|SECRET|TOKEN|PASSWORD|BEGIN PRIVATE KEY|-----BEGIN)", re.I)
ID_RE = re.compile(r"^[0-9A-Za-z._:\-]+$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def die(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    raise SystemExit(1)


def validate_pins(path: Path, arch: str) -> list[str]:
    if not path.is_file():
        die(f"arch {arch}: pin file not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    pins = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not any(ln.split("=", 1)[0].endswith("_IMAGE") for ln in pins):
        die(f"arch {arch}: {path} has no *_IMAGE= entries")
    for ln in pins:
        if SECRET_RE.search(ln):
            die(f"arch {arch}: {path} looks secret-bearing: {ln.split('=', 1)[0]}")
        if not PIN_RE.match(ln):
            die(f"arch {arch}: invalid pin in {path}: {ln}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalog-root", default=".")
    ap.add_argument("--product", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--channel", required=True)
    ap.add_argument(
        "--arch",
        action="append",
        default=[],
        required=True,
        metavar="ARCH=PATH",
        help="Repeatable. e.g. --arch arm64=release_out/manifest.arm64.env",
    )
    ap.add_argument("--release-id", default="")
    ap.add_argument("--source-repo", default="")
    ap.add_argument("--source-sha", default="")
    ap.add_argument("--workflow", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for name, val in (("product", args.product), ("variant", args.variant), ("channel", args.channel)):
        if not SLUG_RE.match(val):
            die(f"{name} must be lower-kebab-case: {val!r}")

    release_id = args.release_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    if not ID_RE.match(release_id):
        die(f"invalid release id: {release_id!r}")

    arch_env: dict[str, Path] = {}
    for spec in args.arch:
        if "=" not in spec:
            die(f"--arch must be ARCH=PATH: {spec!r}")
        arch, raw = spec.split("=", 1)
        if not SLUG_RE.match(arch):
            die(f"invalid arch key: {arch!r}")
        arch_env[arch] = Path(raw)
    if "arm64" not in arch_env:
        die("arm64 is the default fleet arch and must be provided")

    root = Path(args.catalog_root)
    rel_dir = root / "products" / args.product / "releases" / args.variant / release_id
    chan_file = root / "products" / args.product / "channels" / args.variant / f"{args.channel}.txt"

    if rel_dir.exists():
        die(f"release already exists (immutable): {rel_dir}")

    architectures: dict[str, dict[str, str]] = {}
    payloads: dict[str, str] = {}
    for arch, path in sorted(arch_env.items()):
        lines = validate_pins(path, arch)
        env_name = f"manifest.{arch}.env"
        architectures[arch] = {"env": env_name}
        payloads[env_name] = "\n".join(lines).rstrip("\n") + "\n"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    release_json = {
        "product": args.product,
        "variant": args.variant,
        "channel": args.channel,
        "release": release_id,
        "created_utc": now,
        "source": {
            "repo": args.source_repo,
            "sha": args.source_sha,
            "workflow": args.workflow,
            "run_id": args.run_id,
        },
        "architectures": architectures,
    }
    notes = args.notes or (
        f"# {args.product} / {args.variant} — {release_id}\n\n"
        f"Channel: {args.channel}\nArches: {', '.join(sorted(arch_env))}\n"
        f"Source: {args.source_repo}@{args.source_sha}\n"
    )

    if args.dry_run:
        print(f"DRY-RUN would write {rel_dir} and point {chan_file} -> {release_id}", file=sys.stderr)
        print(release_id)
        return 0

    rel_dir.mkdir(parents=True, exist_ok=True)
    (rel_dir / "release.json").write_text(json.dumps(release_json, indent=2) + "\n", encoding="utf-8")
    (rel_dir / "notes.md").write_text(notes, encoding="utf-8")
    for env_name, body in payloads.items():
        (rel_dir / env_name).write_text(body, encoding="utf-8")

    chan_file.parent.mkdir(parents=True, exist_ok=True)
    chan_file.write_text(release_id + "\n", encoding="utf-8")

    print(f"::notice::published {args.product}/{args.variant}/{release_id}; {args.channel} -> {release_id}", file=sys.stderr)
    print(release_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
