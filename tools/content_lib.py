"""Shared helpers for the Kids Discovery World content library.

This module mirrors the validation rules implemented in the application
(`app/src/content/schema.ts`). Anything that validates here will be accepted
by the app, and anything the app rejects is reported as a problem here.

The rules are intentionally duplicated rather than shared, because the content
repository must stay publishable on its own (GitHub Pages serves it) without
the application source code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Iterable

SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1

PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

QUESTION_TYPES = ("multiple-choice", "true-false", "short-answer")

MAX_ENTRY_ID = 96
MAX_PACK_ENTRIES = 2000
MAX_PACK_QUESTIONS = 5000
MAX_PACK_ASSETS = 5000


class ContentError(Exception):
    """Raised when the content cannot be published."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(sha256: str) -> str:
    return sha256[:16]


def is_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_ENTRY_ID and bool(PACK_ID_RE.match(value))


def is_text(value: Any, *, maximum: int = 20000, minimum: int = 1) -> bool:
    return isinstance(value, str) and minimum <= len(value) <= maximum


def _validate_attribution(value: Any, where: str, problems: list[str]) -> None:
    if not isinstance(value, dict):
        problems.append(f"{where}: attribution must be an object")
        return
    if not is_text(value.get("title"), maximum=300):
        problems.append(f"{where}: attribution.title is required")
    if not is_text(value.get("license"), maximum=120):
        problems.append(f"{where}: attribution.license is required")
    if not is_text(value.get("sourceUrl"), maximum=2000):
        problems.append(f"{where}: attribution.sourceUrl is required")
    for key in ("creator", "creatorUrl", "licenseUrl", "modifications"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            problems.append(f"{where}: attribution.{key} must be a string")
    if "attributionRequired" in value and not isinstance(value["attributionRequired"], bool):
        problems.append(f"{where}: attribution.attributionRequired must be true or false")
    allowed = {
        "title",
        "creator",
        "creatorUrl",
        "license",
        "licenseUrl",
        "sourceUrl",
        "attributionRequired",
        "modifications",
    }
    for key in value:
        if key not in allowed:
            problems.append(f"{where}: unknown attribution field '{key}'")


def _validate_entry(entry: Any, where: str, problems: list[str]) -> None:
    if not isinstance(entry, dict):
        problems.append(f"{where}: entry must be an object")
        return
    allowed = {
        "id",
        "title",
        "summary",
        "body",
        "facts",
        "imageIds",
        "keywords",
        "readMinutes",
    }
    for key in entry:
        if key not in allowed:
            problems.append(f"{where}: unknown entry field '{key}'")
    if not is_id(entry.get("id")):
        problems.append(f"{where}: entry.id is missing or invalid")
    if not is_text(entry.get("title"), maximum=200):
        problems.append(f"{where}: entry.title is required")
    if not is_text(entry.get("summary"), maximum=1200):
        problems.append(f"{where}: entry.summary is required")
    if "body" in entry and not isinstance(entry["body"], str):
        problems.append(f"{where}: entry.body must be a string")
    for key in ("facts", "imageIds", "keywords"):
        if key in entry:
            if not isinstance(entry[key], list):
                problems.append(f"{where}: entry.{key} must be a list")
            elif any(not isinstance(item, str) for item in entry[key]):
                problems.append(f"{where}: entry.{key} must only contain strings")
    if "readMinutes" in entry and (
        not isinstance(entry["readMinutes"], int) or not 1 <= entry["readMinutes"] <= 60
    ):
        problems.append(f"{where}: entry.readMinutes must be between 1 and 60")


def _validate_question(question: Any, where: str, problems: list[str]) -> None:
    if not isinstance(question, dict):
        problems.append(f"{where}: question must be an object")
        return
    allowed = {
        "id",
        "type",
        "prompt",
        "explanation",
        "imageId",
        "difficulty",
        "tags",
        "options",
        "answerIndex",
        "answer",
        "acceptedAnswers",
    }
    for key in question:
        if key not in allowed:
            problems.append(f"{where}: unknown question field '{key}'")
    if not is_id(question.get("id")):
        problems.append(f"{where}: question.id is missing or invalid")
    question_type = question.get("type")
    if question_type not in QUESTION_TYPES:
        problems.append(f"{where}: question.type must be one of {QUESTION_TYPES}")
        return
    if not is_text(question.get("prompt"), maximum=2000):
        problems.append(f"{where}: question.prompt is required")
    if "explanation" in question and not isinstance(question["explanation"], str):
        problems.append(f"{where}: question.explanation must be a string")
    if "difficulty" in question and (
        not isinstance(question["difficulty"], int) or not 1 <= question["difficulty"] <= 3
    ):
        problems.append(f"{where}: question.difficulty must be 1, 2 or 3")
    if "tags" in question and (
        not isinstance(question["tags"], list) or any(not isinstance(t, str) for t in question["tags"])
    ):
        problems.append(f"{where}: question.tags must be a list of strings")
    if "imageId" in question and question["imageId"] is not None and not is_id(question["imageId"]):
        problems.append(f"{where}: question.imageId is invalid")

    if question_type == "multiple-choice":
        options = question.get("options")
        if not isinstance(options, list) or not 2 <= len(options) <= 6:
            problems.append(f"{where}: question.options must hold 2 to 6 answers")
        elif any(not is_text(option, maximum=500) for option in options):
            problems.append(f"{where}: question.options must only contain short text")
        answer_index = question.get("answerIndex")
        if not isinstance(answer_index, int) or answer_index < 0:
            problems.append(f"{where}: question.answerIndex must be a positive number")
        elif isinstance(options, list) and answer_index >= len(options):
            problems.append(f"{where}: question.answerIndex points outside the options")
    elif question_type == "true-false":
        if not isinstance(question.get("answer"), bool):
            problems.append(f"{where}: question.answer must be true or false")
    elif question_type == "short-answer":
        accepted = question.get("acceptedAnswers")
        if not isinstance(accepted, list) or not accepted:
            problems.append(f"{where}: question.acceptedAnswers must hold at least one answer")
        elif any(not is_text(answer, maximum=200) for answer in accepted):
            problems.append(f"{where}: question.acceptedAnswers must only contain short text")


def validate_pack(pack: Any, *, source: str = "<pack>") -> list[str]:
    """Return the list of problems in a pack. An empty list means it is valid."""
    problems: list[str] = []
    if not isinstance(pack, dict):
        return [f"{source}: pack must be a JSON object"]

    allowed = {
        "packId",
        "packVersion",
        "schemaVersion",
        "title",
        "description",
        "icon",
        "ageRange",
        "color",
        "entries",
        "questions",
        "assets",
        "attributions",
    }
    for key in pack:
        if key not in allowed:
            problems.append(f"{source}: unknown pack field '{key}'")

    pack_id = pack.get("packId")
    if not is_id(pack_id):
        problems.append(f"{source}: pack.packId is missing or invalid")
    if not isinstance(pack.get("packVersion"), str) or not VERSION_RE.match(pack.get("packVersion", "")):
        problems.append(f"{source}: pack.packVersion must look like 1.0.0")
    if "schemaVersion" in pack and pack["schemaVersion"] != SCHEMA_VERSION:
        problems.append(f"{source}: pack.schemaVersion must be {SCHEMA_VERSION}")
    if not is_text(pack.get("title"), maximum=120):
        problems.append(f"{source}: pack.title is required")
    if "description" in pack and not isinstance(pack["description"], str):
        problems.append(f"{source}: pack.description must be a string")
    if "icon" in pack and not isinstance(pack["icon"], str):
        problems.append(f"{source}: pack.icon must be a string")
    if "color" in pack and (
        not isinstance(pack["color"], str) or not re.match(r"^#[0-9a-fA-F]{6}$", pack["color"])
    ):
        problems.append(f"{source}: pack.color must be a hex colour such as #3b82f6")

    entries = pack.get("entries", [])
    questions = pack.get("questions", [])
    assets = pack.get("assets", [])
    attributions = pack.get("attributions", {})

    if not isinstance(entries, list):
        problems.append(f"{source}: pack.entries must be a list")
        entries = []
    if len(entries) > MAX_PACK_ENTRIES:
        problems.append(f"{source}: too many entries (maximum {MAX_PACK_ENTRIES})")

    if not isinstance(questions, list):
        problems.append(f"{source}: pack.questions must be a list")
        questions = []
    if len(questions) > MAX_PACK_QUESTIONS:
        problems.append(f"{source}: too many questions (maximum {MAX_PACK_QUESTIONS})")

    if not isinstance(assets, list):
        problems.append(f"{source}: pack.assets must be a list")
        assets = []
    if len(assets) > MAX_PACK_ASSETS:
        problems.append(f"{source}: too many assets (maximum {MAX_PACK_ASSETS})")

    if not isinstance(attributions, dict):
        problems.append(f"{source}: pack.attributions must be an object")
        attributions = {}

    entry_ids: set[str] = set()
    for index, entry in enumerate(entries):
        where = f"{source}: entry {index}"
        _validate_entry(entry, where, problems)
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            if entry["id"] in entry_ids:
                problems.append(f"{where}: duplicate entry id '{entry['id']}'")
            entry_ids.add(entry["id"])

    question_ids: set[str] = set()
    for index, question in enumerate(questions):
        where = f"{source}: question {index}"
        _validate_question(question, where, problems)
        if isinstance(question, dict) and isinstance(question.get("id"), str):
            if question["id"] in question_ids:
                problems.append(f"{where}: duplicate question id '{question['id']}'")
            question_ids.add(question["id"])

    asset_ids: set[str] = set()
    asset_by_id: dict[str, dict] = {}
    for index, asset in enumerate(assets):
        where = f"{source}: asset {index}"
        if not isinstance(asset, dict):
            problems.append(f"{where}: asset must be an object")
            continue
        for key in asset:
            if key not in {"id", "full", "thumb", "width", "height", "alt"}:
                problems.append(f"{where}: unknown asset field '{key}'")
        asset_id = asset.get("id")
        if not is_id(asset_id):
            problems.append(f"{where}: asset.id is missing or invalid")
        else:
            if asset_id in asset_ids:
                problems.append(f"{where}: duplicate asset id '{asset_id}'")
            asset_ids.add(asset_id)
            asset_by_id[asset_id] = asset
        for key in ("full", "thumb"):
            if not is_text(asset.get(key), maximum=400):
                problems.append(f"{where}: asset.{key} is required")

    referenced: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            for image_id in entry.get("imageIds", []) or []:
                referenced.add(image_id)
                if image_id not in asset_by_id:
                    problems.append(
                        f"{source}: entry '{entry.get('id')}' uses image '{image_id}' with no asset"
                    )
                if image_id not in attributions:
                    problems.append(
                        f"{source}: entry '{entry.get('id')}' uses image '{image_id}' with no attribution"
                    )
    for question in questions:
        if isinstance(question, dict) and question.get("imageId"):
            image_id = question["imageId"]
            referenced.add(image_id)
            if image_id not in asset_by_id:
                problems.append(f"{source}: question '{question.get('id')}' uses an unknown image")
            if image_id not in attributions:
                problems.append(f"{source}: question '{question.get('id')}' uses an image with no attribution")

    for image_id, attribution in attributions.items():
        _validate_attribution(attribution, f"{source}: attribution '{image_id}'", problems)

    for image_id in sorted(referenced - set(asset_by_id)):
        problems.append(f"{source}: image '{image_id}' is used but never declared in assets")

    return problems


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def find_pack_files(content_dir: str) -> list[str]:
    """Every authored pack file, sorted by path."""
    packs_dir = os.path.join(content_dir, "packs")
    if not os.path.isdir(packs_dir):
        return []
    found: list[str] = []
    for root, _dirs, files in os.walk(packs_dir):
        for name in sorted(files):
            if name.endswith(".src.json"):
                found.append(os.path.join(root, name))
    return sorted(found)


def iter_pack_sources(content_dir: str) -> Iterable[tuple[str, Any]]:
    for path in find_pack_files(content_dir):
        yield path, read_json(path)
