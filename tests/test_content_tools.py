"""Permanent, runnable checks for the content tooling.

These mirror the scenarios the authoring tool and the build enforce, so a
regression in `content_lib.py`, `validate_content.py` or `build_content.py`
shows up here before a child sees it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))

from content_lib import (  # noqa: E402
    APP_VERSION_WITH_RICH_FIELDS,
    compare_versions,
    required_app_version,
    validate_library,
    validate_pack,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, "content")
DIST_DIR = os.path.join(ROOT, "dist")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'} {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


def base_pack() -> dict:
    return {
        "packId": "demo",
        "packVersion": "1.0.0",
        "schemaVersion": 1,
        "title": "Demo",
        "description": "A tiny pack.",
        "icon": "star",
        "ageRange": "6-8",
        "color": "#3b82f6",
        "entries": [
            {
                "id": "topic-1",
                "title": "Topic One",
                "summary": "First topic.",
                "body": "",
                "facts": ["Fact one."],
                "imageIds": [],
                "keywords": ["topic"],
                "readMinutes": 2,
            }
        ],
        "questions": [
            {
                "id": "q-mcq",
                "type": "multiple-choice",
                "prompt": "Pick one.",
                "options": ["A", "B"],
                "answerIndex": 0,
                "explanation": "A is right.",
                "difficulty": 1,
                "tags": [],
            },
            {
                "id": "q-tf",
                "type": "true-false",
                "prompt": "True or false?",
                "answer": True,
                "explanation": "True.",
                "difficulty": 1,
                "tags": [],
            },
            {
                "id": "q-sa",
                "type": "short-answer",
                "prompt": "Type it.",
                "acceptedAnswers": ["Cairo"],
                "explanation": "Cairo.",
                "difficulty": 1,
                "tags": [],
            },
            {
                "id": "q-match",
                "type": "matching",
                "prompt": "Join them.",
                "pairs": [
                    {"left": "Cat", "right": "Meow"},
                    {"left": "Dog", "right": "Woof"},
                ],
                "explanation": "Animals and sounds.",
                "difficulty": 1,
                "tags": [],
            },
        ],
        "assets": [{"id": "lion", "full": "images/lion.webp", "thumb": "images/lion.thumb.webp"}],
        "attributions": {
            "lion": {
                "title": "Lion",
                "creator": "Jane",
                "license": "CC BY 4.0",
                "sourceUrl": "https://example.org/lion.jpg",
                "attributionRequired": True,
            }
        },
    }


# -------------------------------------------------------------- schema rules
pack = base_pack()
check("clean pack validates", not validate_pack(pack))

bad = json.loads(json.dumps(base_pack()))
bad["entries"].append({**bad["entries"][0], "id": "topic-1"})
check("duplicate entry ids rejected", bool(validate_pack(bad)))

bad = json.loads(json.dumps(base_pack()))
bad["entries"][0]["imageIds"] = ["ghost"]
check("image with no asset rejected", bool(validate_pack(bad)))

bad = json.loads(json.dumps(base_pack()))
bad["entries"][0]["imageIds"] = ["lion"]
bad["attributions"] = {}
check("image with no attribution rejected", bool(validate_pack(bad)))

bad = json.loads(json.dumps(base_pack()))
bad["questions"][0]["answerIndex"] = 99
check("bad answerIndex rejected", bool(validate_pack(bad)))

bad = json.loads(json.dumps(base_pack()))
bad["questions"][3]["pairs"] = [{"left": "Cat", "right": "Meow"}, {"left": "Cat", "right": "Woof"}]
check("matching repeated left item rejected", bool(validate_pack(bad)))

bad = json.loads(json.dumps(base_pack()))
bad["questions"][3]["pairs"] = [{"left": "Cat", "right": "Meow"}]
check("matching needs at least 2 pairs rejected", bool(validate_pack(bad)))

good = json.loads(json.dumps(base_pack()))
good["entries"][0]["ageLevel"] = "6-8"
good["entries"][0]["difficulty"] = 2
good["entries"][0]["learningObjectives"] = ["Learn something"]
good["entries"][0]["vocabulary"] = [{"term": "savanna", "definition": "wide grassland"}]
good["entries"][0]["sources"] = ["https://example.org/src"]
good["entries"][0]["relatedIds"] = []
good["entries"][0]["extra"] = {"habitat": "savanna"}
check("rich fields are accepted", not validate_pack(good))

# -------------------------------------------------------------- compatibility
check("rich fields need app 1.1.0", required_app_version(good) == APP_VERSION_WITH_RICH_FIELDS)

classic = json.loads(json.dumps(base_pack()))
classic["questions"] = [q for q in classic["questions"] if q["type"] != "matching"]
classic["entries"][0].pop("ageLevel", None)
check("classic pack needs no version", required_app_version(classic) is None)

match_pack = json.loads(json.dumps(classic))
match_pack["questions"][0]["type"] = "matching"
check("matching needs app 1.1.0", required_app_version(match_pack) == APP_VERSION_WITH_RICH_FIELDS)

# -------------------------------------------------------------- library rules
library_packs = [base_pack(), json.loads(json.dumps({**base_pack(), "packId": "demo2", "title": "Demo 2"}))]
check("two packs are fine", not validate_library(library_packs))
dup = json.loads(json.dumps(base_pack()))
dup["packId"] = "demo"
check("duplicate pack id rejected", bool(validate_library([base_pack(), dup])))

# -------------------------------------------------------------- end-to-end build
tmp = tempfile.mkdtemp(prefix="kdw-tools-test-")
try:
    tmp_content = os.path.join(tmp, "content")
    tmp_dist = os.path.join(tmp, "dist")
    shutil.copytree(CONTENT_DIR, tmp_content)
    # Introduce one deliberate picture error so the build must refuse.
    bad_pack = os.path.join(tmp_content, "packs", "animal-kingdom", "animal-kingdom.src.json")
    content = json.load(open(bad_pack, encoding="utf-8"))
    content["entries"][0]["imageIds"] = ["ghost-image"]
    json.dump(content, open(bad_pack, "w", encoding="utf-8"))

    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "build_content.py"),
         "--content-dir", tmp_content, "--out-dir", tmp_dist],
        capture_output=True, text=True, encoding="utf-8",
    )
    check("build refuses a missing image", result.returncode != 0, result.stdout[:200])

    # Restore the original pack from the real content dir, then build twice.
    good_pack = os.path.join(tmp_content, "packs", "animal-kingdom", "animal-kingdom.src.json")
    original_pack = os.path.join(CONTENT_DIR, "packs", "animal-kingdom", "animal-kingdom.src.json")
    shutil.copy2(original_pack, good_pack)

    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "build_content.py"),
         "--content-dir", tmp_content, "--out-dir", tmp_dist],
        capture_output=True, text=True, encoding="utf-8",
    )
    check("clean content builds", result.returncode == 0, result.stderr[:200])

    manifest = json.load(open(os.path.join(tmp_dist, "manifest.json"), encoding="utf-8"))
    report = json.load(open(os.path.join(tmp_dist, "build-report.json"), encoding="utf-8"))
    check("manifest has 25 packs", len(manifest["packs"]) == 25)
    check("previous build recorded as none", report["previousBuild"] == "none")

    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "build_content.py"),
         "--content-dir", tmp_content, "--out-dir", tmp_dist],
        capture_output=True, text=True, encoding="utf-8",
    )
    report2 = json.load(open(os.path.join(tmp_dist, "build-report.json"), encoding="utf-8"))
    check("unchanged rebuild reports nothing new",
          report2["previousBuild"] == "dist/manifest.json"
          and not report2["addedPacks"] and not report2["changedPacks"] and not report2["removedPacks"]
          and report2["downloadBytes"] == 0)

    # Min app version gate: content uses rich fields but library promises 1.0.0.
    with open(os.path.join(tmp_content, "library.json"), encoding="utf-8") as handle:
        library = json.load(handle)
    library["minAppVersion"] = "1.0.0"
    json.dump(library, open(os.path.join(tmp_content, "library.json"), "w", encoding="utf-8"))
    rich_pack = os.path.join(tmp_content, "packs", "animal-kingdom", "animal-kingdom.src.json")
    rich = json.load(open(rich_pack, encoding="utf-8"))
    rich["entries"][0]["ageLevel"] = "6-8"
    json.dump(rich, open(rich_pack, "w", encoding="utf-8"))
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "build_content.py"),
         "--content-dir", tmp_content, "--out-dir", tmp_dist],
        capture_output=True, text=True, encoding="utf-8",
    )
    check("build blocks outdated minAppVersion", result.returncode != 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print(f"APP_VERSION_WITH_RICH_FIELDS = {APP_VERSION_WITH_RICH_FIELDS}")
print("ALL CONTENT TOOL TESTS PASSED")
