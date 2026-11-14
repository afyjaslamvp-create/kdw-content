"""Validate every authored content pack and the library as a whole.

Run before publishing:

    python tools/validate_content.py

Exit code 0 means the content is publishable. Besides checking each pack on
its own, this looks at the library the way the application downloads it:
duplicated pack ids, picture files that are missing or empty, pictures with
no licence details, conflicting licences for the same picture, and whether
the declared minimum app version is new enough for the content it contains.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_lib import (  # noqa: E402
    compare_versions,
    find_pack_files,
    read_json,
    required_app_version,
    validate_library,
    validate_pack,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(os.path.dirname(HERE), "content")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Kids Discovery World content.")
    parser.add_argument(
        "--content-dir",
        default=CONTENT_DIR,
        help="Folder that holds the authored packs (default: content/).",
    )
    args = parser.parse_args()

    pack_files = find_pack_files(args.content_dir)
    if not pack_files:
        print(f"No pack files found in {args.content_dir}", file=sys.stderr)
        return 1

    packs: list[dict] = []
    total_problems = 0
    total_entries = 0
    total_questions = 0
    total_assets = 0

    for path in pack_files:
        relative = os.path.relpath(path, args.content_dir)
        try:
            pack = read_json(path)
        except json.JSONDecodeError as error:
            print(f"FAIL {relative}: could not read the file ({error})")
            total_problems += 1
            continue

        packs.append(pack)
        problems = validate_pack(pack, source=relative)
        if isinstance(pack, dict):
            total_entries += len(pack.get("entries", []) or [])
            total_questions += len(pack.get("questions", []) or [])
            total_assets += len(pack.get("assets", []) or [])

        if problems:
            total_problems += len(problems)
            print(f"FAIL {relative}")
            for problem in problems:
                print(f"     - {problem}")
        else:
            title = pack.get("title") if isinstance(pack, dict) else "?"
            version = pack.get("packVersion") if isinstance(pack, dict) else "?"
            print(f"ok   {relative}: {title} v{version}")

    print()
    print("library-wide checks")

    library_problems = validate_library(packs, content_dir=args.content_dir)
    for problem in library_problems:
        total_problems += 1
        print(f"FAIL library: {problem}")
    if not library_problems:
        print("ok   pack ids are unique and picture files all exist")

    # Licence details: every picture must carry them, and the app shows them
    # to the child, so it is worth knowing how many need an on screen credit.
    attributed = 0
    credited = 0
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        attributions = pack.get("attributions") or {}
        for asset in pack.get("assets", []) or []:
            if not isinstance(asset, dict):
                continue
            attribution = attributions.get(asset.get("id"))
            if isinstance(attribution, dict):
                attributed += 1
                if attribution.get("attributionRequired", True):
                    credited += 1
    if total_assets:
        print(
            f"note {attributed}/{total_assets} pictures carry licence details "
            f"({credited} need an on screen credit)"
        )

    # Which app version does the content need?
    required_by_pack: list[tuple[str, str]] = []
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        needed = required_app_version(pack)
        if needed is not None:
            required_by_pack.append((str(pack.get("packId", "<unknown>")), needed))
    if required_by_pack:
        newest = max(version for _pack_id, version in required_by_pack)
        print(
            f"note {len(required_by_pack)} pack(s) use newer content features and "
            f"need app version {newest} or newer"
        )
    else:
        print("note every pack can be read by the original app (1.0.0 or newer)")

    # The library file itself.
    library_path = os.path.join(args.content_dir, "library.json")
    if not os.path.exists(library_path):
        print("FAIL library.json is missing")
        total_problems += 1
    else:
        try:
            library = read_json(library_path)
        except json.JSONDecodeError as error:
            print(f"FAIL library.json: invalid JSON ({error})")
            total_problems += 1
        else:
            if not library.get("libraryVersion"):
                print("FAIL library.json: libraryVersion is required")
                total_problems += 1
            if (
                not isinstance(library.get("libraryVersionNumber"), int)
                or library.get("libraryVersionNumber", 0) < 1
            ):
                print(
                    "FAIL library.json: libraryVersionNumber must be a whole number of at least 1"
                )
                total_problems += 1

            declared_min = library.get("minAppVersion", "1.0.0")
            if not isinstance(declared_min, str) or not declared_min:
                print("FAIL library.json: minAppVersion is required")
                total_problems += 1
            else:
                newest_needed = None
                for _pack_id, version in required_by_pack:
                    if newest_needed is None or compare_versions(version, newest_needed) > 0:
                        newest_needed = version
                if newest_needed and compare_versions(declared_min, newest_needed) < 0:
                    print(
                        f"FAIL library.json: minAppVersion {declared_min} is too old for this "
                        f"content - raise it to {newest_needed}"
                    )
                    total_problems += 1
                else:
                    print(
                        f"ok   library {library.get('libraryVersion')} "
                        f"(#{library.get('libraryVersionNumber')}), min app {declared_min}"
                    )

    print()
    print(
        f"{len(pack_files)} pack(s), {total_entries} topics, "
        f"{total_questions} questions, {total_assets} pictures"
    )
    if total_problems:
        print(f"{total_problems} problem(s) found - the content cannot be published yet.")
        return 1
    print("All content is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
