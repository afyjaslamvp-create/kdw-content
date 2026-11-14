"""Build the publishable content library.

Validates every authored pack, copies the images into a content addressed
layout, writes the published pack files and finally writes `manifest.json`.

    python tools/build_content.py

The result is written to `dist/`, which is the folder GitHub Pages serves.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_lib import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    ContentError,
    find_pack_files,
    read_json,
    sha256_bytes,
    sha256_file,
    short_hash,
    validate_pack,
    write_json,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENT_DIR = os.path.join(ROOT, "content")
DIST_DIR = os.path.join(ROOT, "dist")


def version_number(version: str) -> int:
    """Turn 1.2.3 into a number that always grows when the version grows."""
    parts = [int(part) for part in version.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 10000 + parts[1] * 100 + parts[2]


def build(args: argparse.Namespace) -> int:
    library_path = os.path.join(args.content_dir, "library.json")
    if not os.path.exists(library_path):
        print(f"No library.json found at {library_path}", file=sys.stderr)
        return 1
    library = read_json(library_path)

    pack_files = find_pack_files(args.content_dir)
    if not pack_files:
        print(f"No pack files found in {args.content_dir}", file=sys.stderr)
        return 1

    # Validate everything first: a single broken pack must not produce a
    # half published library.
    problems: list[str] = []
    for path in pack_files:
        relative = os.path.relpath(path, args.content_dir)
        try:
            pack = read_json(path)
        except json.JSONDecodeError as error:
            problems.append(f"{relative}: invalid JSON ({error})")
            continue
        problems.extend(validate_pack(pack, source=relative))

    if problems:
        print("The content cannot be published:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if os.path.isdir(args.out_dir):
        shutil.rmtree(args.out_dir)
    os.makedirs(os.path.join(args.out_dir, "packs"), exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "images"), exist_ok=True)

    published_images: dict[str, dict] = {}
    manifest_packs: list[dict] = []

    for path in pack_files:
        pack = read_json(path)
        pack_id = pack["packId"]
        version = pack["packVersion"]

        # Copy the images into a content addressed layout and rewrite the
        # paths in the published pack.
        published_pack = json.loads(json.dumps(pack))
        published_pack.setdefault("schemaVersion", SCHEMA_VERSION)
        files: list[dict] = []

        for asset in published_pack.get("assets", []):
            for kind, source_key in (("image-full", "full"), ("image-thumb", "thumb")):
                source_rel = asset[source_key]
                source_path = os.path.join(args.content_dir, source_rel)
                if not os.path.exists(source_path):
                    raise ContentError(f"{pack_id}: image file not found: {source_rel}")
                digest = sha256_file(source_path)
                target_name = f"{short_hash(digest)}" + (
                    ".thumb.webp" if kind == "image-thumb" else ".webp"
                )
                target_rel = f"images/{target_name}"
                target_path = os.path.join(args.out_dir, target_rel)
                if not os.path.exists(target_path):
                    shutil.copy2(source_path, target_path)
                published_images[target_rel] = {
                    "path": target_rel,
                    "bytes": os.path.getsize(target_path),
                    "sha256": digest,
                    "kind": kind,
                }
                asset[source_key] = target_rel

        # The pack payload itself.
        data_rel = f"packs/{pack_id}/{pack_id}.v{version}.json"
        data_path = os.path.join(args.out_dir, data_rel)
        payload = json.dumps(published_pack, ensure_ascii=False, indent=2).encode("utf-8")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        with open(data_path, "wb") as handle:
            handle.write(payload)
        files.append(
            {
                "path": data_rel,
                "bytes": len(payload),
                "sha256": sha256_bytes(payload),
                "kind": "data",
            }
        )

        for asset in published_pack.get("assets", []):
            for source_key in ("full", "thumb"):
                target_rel = asset[source_key]
                info = published_images[target_rel]
                files.append(
                    {
                        "path": info["path"],
                        "bytes": info["bytes"],
                        "sha256": info["sha256"],
                        "kind": info["kind"],
                    }
                )

        total_bytes = sum(item["bytes"] for item in files)
        manifest_packs.append(
            {
                "id": pack_id,
                "title": pack["title"],
                "description": pack.get("description", ""),
                "icon": pack.get("icon", "star"),
                "color": pack.get("color", "#3b82f6"),
                "version": version,
                "versionNumber": version_number(version),
                "required": False,
                "dependencies": [],
                "files": files,
                "counts": {
                    "entries": len(pack.get("entries", [])),
                    "questions": len(pack.get("questions", [])),
                },
                "totalBytes": total_bytes,
            }
        )
        print(
            f"built {pack_id} v{version}: {len(pack.get('entries', []))} topics, "
            f"{len(pack.get('questions', []))} questions, {total_bytes / 1024:.0f} KB"
        )

    manifest_packs.sort(key=lambda item: item["title"])

    manifest = {
        "manifestVersion": MANIFEST_SCHEMA_VERSION,
        "libraryVersion": library["libraryVersion"],
        "libraryVersionNumber": library.get("libraryVersionNumber", 1),
        "minAppVersion": library.get("minAppVersion", "1.0.0"),
        "generatedAt": library.get("generatedAt") or _utc_now(),
        "packs": manifest_packs,
    }
    write_json(os.path.join(args.out_dir, "manifest.json"), manifest)

    total = sum(pack["totalBytes"] for pack in manifest_packs)
    print()
    print(f"manifest.json written with {len(manifest_packs)} pack(s), {total / 1024:.0f} KB total")
    print(f"publish folder: {args.out_dir}")
    return 0


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the content library.")
    parser.add_argument("--content-dir", default=CONTENT_DIR)
    parser.add_argument("--out-dir", default=DIST_DIR)
    args = parser.parse_args()
    try:
        return build(args)
    except ContentError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
