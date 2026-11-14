"""Validate every authored content pack.

Run before publishing:

    python tools/validate_content.py

Exit code 0 means the content is publishable.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_lib import find_pack_files, read_json, validate_pack  # noqa: E402

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

    total_problems = 0
    total_entries = 0
    total_questions = 0

    for path in pack_files:
        relative = os.path.relpath(path, args.content_dir)
        try:
            pack = read_json(path)
        except json_error() as error:  # type: ignore[misc]
            print(f"FAIL {relative}: could not read the file ({error})")
            total_problems += 1
            continue

        problems = validate_pack(pack, source=relative)
        entries = len(pack.get("entries", []) or []) if isinstance(pack, dict) else 0
        questions = len(pack.get("questions", []) or []) if isinstance(pack, dict) else 0
        total_entries += entries
        total_questions += questions

        if problems:
            total_problems += len(problems)
            print(f"FAIL {relative}")
            for problem in problems:
                print(f"     - {problem}")
        else:
            print(
                f"ok   {relative}: {pack.get('title')} v{pack.get('packVersion')} "
                f"({entries} topics, {questions} questions)"
            )

    print()
    print(f"{len(pack_files)} pack(s), {total_entries} topics, {total_questions} questions")
    if total_problems:
        print(f"{total_problems} problem(s) found - the content cannot be published yet.")
        return 1
    print("All content is valid.")
    return 0


def json_error():
    import json

    return json.JSONDecodeError


if __name__ == "__main__":
    raise SystemExit(main())
