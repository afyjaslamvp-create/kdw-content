"""Build the publishable content library.

Validates every authored pack (and the library as a whole), copies the images
into a content addressed layout, writes the published pack files and finally
writes `manifest.json`.

    python tools/build_content.py

The result is written to `dist/`, which is the folder GitHub Pages serves.

Before the build wipes `dist/`, the last published manifest is remembered so
the build can report exactly which packs and files changed. That is how the
application works out what to download: unchanged files are never re-sent.
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
    compare_versions,
    find_pack_files,
    read_json,
    required_app_version,
    sha256_bytes,
    sha256_file,
    short_hash,
    validate_library,
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


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def collect_packs(content_dir: str) -> tuple[list[dict], list[str]]:
    """Read every pack file and validate it. Returns (packs, problems)."""
    pack_files = find_pack_files(content_dir)
    packs: list[dict] = []
    problems: list[str] = []
    for path in pack_files:
        relative = os.path.relpath(path, content_dir)
        try:
            pack = read_json(path)
        except json.JSONDecodeError as error:
            problems.append(f"{relative}: invalid JSON ({error})")
            continue
        packs.append(pack)
        problems.extend(validate_pack(pack, source=relative))
    return packs, problems


def check_publishable(content_dir: str, packs: list[dict]) -> list[str]:
    """Everything that stops the library from being published.

    In addition to the per pack checks this looks at the library as a whole:
    duplicated pack ids, missing picture files, missing licence details, and
    whether the library version is new enough for the installed apps to notice
    the change.
    """
    problems: list[str] = validate_library(packs, content_dir=content_dir)

    library_path = os.path.join(content_dir, "library.json")
    if not os.path.exists(library_path):
        problems.append("content/library.json is missing")
        return problems
    try:
        library = read_json(library_path)
    except json.JSONDecodeError as error:
        problems.append(f"content/library.json: invalid JSON ({error})")
        return problems

    # The app needs to notice that the library changed. If the library version
    # did not move on, installed apps will not see the new content.
    if not library.get("libraryVersion"):
        problems.append("library.json: libraryVersion is required")
    if not isinstance(library.get("libraryVersionNumber"), int) or library.get("libraryVersionNumber", 0) < 1:
        problems.append("library.json: libraryVersionNumber must be a whole number of at least 1")

    # A pack may only use fields that the library promises the app can read.
    declared_min = library.get("minAppVersion", "1.0.0")
    if not isinstance(declared_min, str) or not declared_min:
        problems.append("library.json: minAppVersion is required")
        declared_min = "1.0.0"
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        needed = required_app_version(pack)
        if needed is None:
            continue
        if compare_versions(declared_min, needed) < 0:
            pack_id = pack.get("packId", "<unknown>")
            problems.append(
                f"library.json: pack '{pack_id}' uses newer content features that need "
                f"app version {needed} or newer, but the library only promises "
                f"minAppVersion {declared_min}. Raise minAppVersion in library.json to "
                f"{needed} (installed apps get the newer app automatically - no new APK)."
            )
    return problems


def previous_manifest(dist_dir: str) -> dict | None:
    """The manifest of the last published build, if one is in dist/."""
    path = os.path.join(dist_dir, "manifest.json")
    if not os.path.exists(path):
        return None
    try:
        return read_json(path)
    except json.JSONDecodeError:
        return None


def diff_manifests(previous: dict | None, current: dict) -> dict:
    """Which packs and files changed between two builds."""
    current_files: dict[str, dict] = {}
    for pack in current["packs"]:
        for file in pack["files"]:
            current_files[file["path"]] = file

    previous_files: dict[str, dict] = {}
    previous_pack_ids: set[str] = set()
    if previous:
        for pack in previous.get("packs", []):
            previous_pack_ids.add(pack["id"])
            for file in pack.get("files", []):
                previous_files[file["path"]] = file
    current_pack_ids = {pack["id"] for pack in current["packs"]}

    added = sorted(path for path in current_files if path not in previous_files)
    removed = sorted(path for path in previous_files if path not in current_files)
    changed = sorted(
        path
        for path, file in current_files.items()
        if path in previous_files and previous_files[path]["sha256"] != file["sha256"]
    )

    return {
        "addedPacks": sorted(current_pack_ids - previous_pack_ids),
        "removedPacks": sorted(previous_pack_ids - current_pack_ids),
        "changedPacks": sorted(
            pack_id
            for pack_id in current_pack_ids & previous_pack_ids
            if any(
                file["path"].startswith(f"packs/{pack_id}/") and file["path"] in changed
                for file in current_files.values()
            )
        ),
        "addedFiles": added,
        "changedFiles": changed,
        "removedFiles": removed,
        "downloadBytes": sum(current_files[path]["bytes"] for path in added + changed),
    }


def build(args: argparse.Namespace) -> int:
    library_path = os.path.join(args.content_dir, "library.json")
    if not os.path.exists(library_path):
        print(f"No library.json found at {library_path}", file=sys.stderr)
        return 1
    library = read_json(library_path)

    packs, problems = collect_packs(args.content_dir)
    if not packs:
        print(f"No pack files found in {args.content_dir}", file=sys.stderr)
        return 1

    # Validate everything first: a single broken pack must not produce a
    # half published library.
    problems.extend(check_publishable(args.content_dir, packs))
    if problems:
        print("The content cannot be published:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    # Remember the last published build before the folder is wiped, so the
    # build can say exactly what changed.
    last_manifest = previous_manifest(args.out_dir)

    if os.path.isdir(args.out_dir):
        shutil.rmtree(args.out_dir)
    os.makedirs(os.path.join(args.out_dir, "packs"), exist_ok=True)
    os.makedirs(os.path.join(args.out_dir, "images"), exist_ok=True)

    published_images: dict[str, dict] = {}
    manifest_packs: list[dict] = []

    for pack in packs:
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

    change_report = diff_manifests(last_manifest, manifest)
    report = {
        "libraryVersion": manifest["libraryVersion"],
        "libraryVersionNumber": manifest["libraryVersionNumber"],
        "minAppVersion": manifest["minAppVersion"],
        "previousBuild": "none" if last_manifest is None else "dist/manifest.json",
        **change_report,
    }
    write_json(os.path.join(args.out_dir, "build-report.json"), report)

    total = sum(pack["totalBytes"] for pack in manifest_packs)
    print()
    print(
        f"manifest.json written with {len(manifest_packs)} pack(s), {total / 1024:.0f} KB total "
        f"(library {manifest['libraryVersion']}, min app {manifest['minAppVersion']})"
    )
    print()
    if last_manifest is None:
        print("change report: first build - every file is new")
    else:
        if not (
            change_report["addedPacks"]
            or change_report["changedPacks"]
            or change_report["removedPacks"]
        ):
            print("change report: nothing changed - no new files for kids to download")
        else:
            for kind in ("addedPacks", "changedPacks", "removedPacks"):
                for pack_id in change_report[kind]:
                    print(f"  {kind.rstrip('s')}: {pack_id}")
            for path in change_report["addedFiles"]:
                print(f"  + {path}")
            for path in change_report["changedFiles"]:
                print(f"  ~ {path}")
            for path in change_report["removedFiles"]:
                print(f"  - {path}")
            print(
                f"  new downloads for kids: "
                f"{change_report['downloadBytes'] / 1024:.0f} KB "
                f"({len(change_report['addedFiles']) + len(change_report['changedFiles'])} file(s))"
            )
    print(f"build report: {os.path.join(args.out_dir, 'build-report.json')}")
    print(f"publish folder: {args.out_dir}")
    return 0


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
