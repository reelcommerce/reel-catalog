#!/usr/bin/env python3
"""
publish.py — write an immutable release into reel-catalog and move a channel.

Catalog engine for `reel catalog publish`. Invoked by the Reel CLI or by
product CIs (reel-docker, reel-builder, reel-edge, reel-os) that have checked
out the catalog repo. Given one or more arch pin files and/or OS-image
descriptors, it writes:

    products/<product>/releases/<variant>/<release-id>/
        release.json
        manifest.<arch>.env      (one per --arch <arch>=<path>, docker pins)
        image.<arch>.json        (one per --asset <arch>=<path>, OS image or shell)
        content.json             (one per --content, IPFS application)
        notes.md
    products/<product>/channels/<variant>/<channel>.txt   (-> release-id)

Usage (docker pins — reel-docker / reel-builder):
  python3 scripts/publish.py \\
    --catalog-root . \\
    --product reel-builder --variant builder --channel stable \\
    --arch arm64=release_out/manifest.arm64.env \\
    [--arch amd64=release_out/manifest.amd64.env] \\
    --source-repo reelcommerce/reel-builder --source-sha "$GIT_SHA" \\
    --workflow ci-release --run-id "$RUN_ID" \\
    [--release-id 2026-07-17T0815Z] [--notes "text"] [--dry-run]

Usage (OS image — reel-os):
  python3 scripts/publish.py \\
    --catalog-root . \\
    --product reel-os --variant site-beckenham-london-uk --channel stable \\
    --asset arm64=release_out/image.arm64.json \\
    --source-repo reelcommerce/reel-os --source-sha "$GIT_SHA" \\
    --workflow build-image --run-id "$RUN_ID"

At least one of --arch / --asset / --content is required. Docker pins
(--arch) are arm64 and/or amd64. OS images use --asset arm64 or amd64.
Reel shells (reel-shell) use --asset with an installer platform: win-x64,
darwin-x64, darwin-arm64, linux-x64, linux-arm64, android-tv,
android-mobile. Reel applications (reel-app) use --content for an IPFS
CID. A content release does not include docker pins or installer assets.

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
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
FLEET_ARCHES = frozenset({"arm64", "amd64"})
# reel-shell installer pointers (image.<platform>.json). Not docker arches.
INSTALLER_PLATFORMS = frozenset({
    "win-x64",
    "darwin-x64",
    "darwin-arm64",
    "linux-x64",
    "linux-arm64",
    "android-tv",
    "android-mobile",
})


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


def validate_asset(path: Path, arch: str) -> dict:
    """Validate an OS-image artifact descriptor (JSON) for a non-pin release.

    Required: filename, sha256 (64 hex), url (https). Optional: bytes, tag.
    """
    if not path.is_file():
        die(f"arch {arch}: asset descriptor not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"arch {arch}: asset descriptor is not valid JSON: {exc}")
    if not isinstance(data, dict):
        die(f"arch {arch}: asset descriptor must be a JSON object")
    filename = str(data.get("filename", "")).strip()
    sha256 = str(data.get("sha256", "")).strip().lower()
    url = str(data.get("url", "")).strip()
    if not filename:
        die(f"arch {arch}: asset missing 'filename'")
    if not SHA256_RE.match(sha256):
        die(f"arch {arch}: asset 'sha256' must be 64 hex chars: {sha256!r}")
    if not url.startswith("https://"):
        die(f"arch {arch}: asset 'url' must be https://: {url!r}")
    for key in ("filename", "url"):
        if SECRET_RE.search(str(data.get(key, ""))):
            die(f"arch {arch}: asset field {key} looks secret-bearing")
    out = {"filename": filename, "sha256": sha256, "url": url}
    if "bytes" in data:
        try:
            out["bytes"] = int(data["bytes"])
        except (TypeError, ValueError):
            die(f"arch {arch}: asset 'bytes' must be an integer")
    if data.get("tag"):
        out["tag"] = str(data["tag"]).strip()
    return out


CID_RE = re.compile(r"^(Qm[1-9A-HJ-NP-Za-km-z]{44,}|ba[a-z2-7]{20,})$")
IPNS_RE = re.compile(r"^[A-Za-z0-9]{10,}$")


def validate_content(path: Path) -> dict:
    """Validate an IPFS application descriptor (reel-app content.json).

    Required: cid, ipns, sha256. Optional: url (https gateway).
    """
    if not path.is_file():
        die(f"content descriptor not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"content descriptor is not valid JSON: {exc}")
    if not isinstance(data, dict):
        die("content descriptor must be a JSON object")
    cid = str(data.get("cid", "")).strip()
    ipns = str(data.get("ipns", "")).strip().removeprefix("/ipns/")
    sha256 = str(data.get("sha256", "")).strip().lower()
    if not CID_RE.match(cid):
        die(f"content 'cid' is not a CID: {cid!r}")
    if not IPNS_RE.match(ipns):
        die(f"content 'ipns' must be the IPNS name: {ipns!r}")
    if not SHA256_RE.match(sha256):
        die(f"content 'sha256' must be 64 hex chars: {sha256!r}")
    for key in ("cid", "ipns"):
        if SECRET_RE.search(str(data.get(key, ""))):
            die(f"content field {key} looks secret-bearing")
    out = {"cid": cid, "ipns": ipns, "sha256": sha256}
    if data.get("url"):
        url = str(data["url"]).strip()
        if not url.startswith("https://"):
            die(f"content 'url' must be https://: {url!r}")
        if SECRET_RE.search(url):
            die("content field url looks secret-bearing")
        out["url"] = url
    return out


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
        metavar="ARCH=PATH",
        help="Repeatable docker-pin manifest. e.g. --arch arm64=release_out/manifest.arm64.env",
    )
    ap.add_argument(
        "--asset",
        action="append",
        default=[],
        metavar="ARCH=PATH",
        help=(
            "Repeatable asset descriptor JSON. "
            "e.g. --asset arm64=release_out/image.arm64.json "
            "or --asset win-x64=release_out/image.win-x64.json"
        ),
    )
    ap.add_argument(
        "--content",
        default="",
        metavar="PATH",
        help="IPFS application descriptor. e.g. --content release_out/content.json",
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

    def parse_specs(specs: list[str], flag: str) -> dict[str, Path]:
        out: dict[str, Path] = {}
        for spec in specs:
            if "=" not in spec:
                die(f"{flag} must be ARCH=PATH: {spec!r}")
            arch, raw = spec.split("=", 1)
            if not SLUG_RE.match(arch):
                die(f"invalid arch key: {arch!r}")
            out[arch] = Path(raw)
        return out

    arch_env = parse_specs(args.arch, "--arch")
    asset_json = parse_specs(args.asset, "--asset")
    content = validate_content(Path(args.content)) if args.content else None
    if content and (arch_env or asset_json):
        die("a content release cannot include --arch or --asset")
    if not arch_env and not asset_json and content is None:
        die("provide --arch (docker pins), --asset (OS image or installer), or --content (IPFS app)")
    for arch in arch_env:
        if arch not in FLEET_ARCHES:
            die(f"docker pin arch must be arm64 or amd64, got {arch}")
    allowed_assets = FLEET_ARCHES | INSTALLER_PLATFORMS
    for arch in asset_json:
        if arch not in allowed_assets:
            die(
                "asset platform must be arm64, amd64, or an installer platform "
                f"({', '.join(sorted(INSTALLER_PLATFORMS))}), got {arch}"
            )
    all_arches = set(arch_env) | set(asset_json)

    root = Path(args.catalog_root)
    rel_dir = root / "products" / args.product / "releases" / args.variant / release_id
    chan_file = root / "products" / args.product / "channels" / args.variant / f"{args.channel}.txt"

    if rel_dir.exists():
        die(f"release already exists (immutable): {rel_dir}")

    architectures: dict[str, dict[str, str]] = {}
    payloads: dict[str, str] = {}
    for arch in sorted(all_arches):
        entry: dict[str, str] = {}
        if arch in arch_env:
            lines = validate_pins(arch_env[arch], arch)
            env_name = f"manifest.{arch}.env"
            entry["env"] = env_name
            payloads[env_name] = "\n".join(lines).rstrip("\n") + "\n"
        if arch in asset_json:
            asset = validate_asset(asset_json[arch], arch)
            img_name = f"image.{arch}.json"
            entry["image"] = img_name
            payloads[img_name] = json.dumps(asset, indent=2) + "\n"
        architectures[arch] = entry

    if content is not None:
        payloads["content.json"] = json.dumps(content, indent=2) + "\n"

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
    }
    if architectures:
        release_json["architectures"] = architectures
    if content is not None:
        release_json["content"] = "content.json"
    detail = (
        f"Content: {content['cid']}"
        if content is not None
        else f"Arches: {', '.join(sorted(all_arches))}"
    )
    notes = args.notes or (
        f"# {args.product} / {args.variant} — {release_id}\n\n"
        f"Channel: {args.channel}\n{detail}\n"
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
