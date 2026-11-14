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

# The first app version that understands the richer entry fields and the
# matching question type. Content that uses them must not be published for an
# older app, so the build refuses to publish it unless `library.json` asks for
# at least this app version.
APP_VERSION_WITH_RICH_FIELDS = "1.1.0"

PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

QUESTION_TYPES = ("multiple-choice", "true-false", "short-answer", "matching", "ordering")

# Entry fields that were added after the first release of the app.
RICH_ENTRY_FIELDS = (
    "ageLevel",
    "difficulty",
    "learningObjectives",
    "vocabulary",
    "sources",
    "relatedIds",
    "extra",
    "introduction",
    "curiosityQuestion",
    "grade1",
    "grade2",
    "sections",
    "diagrams",
)

MAX_ENTRY_ID = 96
MAX_PACK_ENTRIES = 2000
MAX_PACK_QUESTIONS = 5000
MAX_PACK_ASSETS = 5000
MAX_MATCHING_PAIRS = 8
MAX_VOCABULARY_TERMS = 20
MAX_SECTIONS = 20
MAX_DIAGRAMS = 10
MAX_ORDERING_ITEMS = 8


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
        "ageLevel",
        "difficulty",
        "learningObjectives",
        "vocabulary",
        "sources",
        "relatedIds",
        "extra",
        "introduction",
        "curiosityQuestion",
        "grade1",
        "grade2",
        "sections",
        "diagrams",
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
    if "ageLevel" in entry and not is_text(entry["ageLevel"], maximum=40):
        problems.append(f"{where}: entry.ageLevel must be short text such as '6-8'")
    if "difficulty" in entry and (
        not isinstance(entry["difficulty"], int) or not 1 <= entry["difficulty"] <= 3
    ):
        problems.append(f"{where}: entry.difficulty must be 1, 2 or 3")
    if "learningObjectives" in entry:
        objectives = entry["learningObjectives"]
        if not isinstance(objectives, list):
            problems.append(f"{where}: entry.learningObjectives must be a list")
        elif len(objectives) > 10:
            problems.append(f"{where}: entry.learningObjectives may hold at most 10 items")
        elif any(not is_text(item, maximum=300) for item in objectives):
            problems.append(f"{where}: entry.learningObjectives must only contain short text")
    if "vocabulary" in entry:
        vocabulary = entry["vocabulary"]
        if not isinstance(vocabulary, list):
            problems.append(f"{where}: entry.vocabulary must be a list")
        elif len(vocabulary) > MAX_VOCABULARY_TERMS:
            problems.append(
                f"{where}: entry.vocabulary may hold at most {MAX_VOCABULARY_TERMS} words"
            )
        else:
            for position, word in enumerate(vocabulary):
                if not isinstance(word, dict):
                    problems.append(f"{where}: vocabulary word {position + 1} must be an object")
                    continue
                for key in word:
                    if key not in {"term", "definition", "pronunciation"}:
                        problems.append(
                            f"{where}: vocabulary word {position + 1} has unknown field '{key}'"
                        )
                if not is_text(word.get("term"), maximum=120):
                    problems.append(f"{where}: vocabulary word {position + 1} needs a term")
                if not is_text(word.get("definition"), maximum=600):
                    problems.append(f"{where}: vocabulary word {position + 1} needs a definition")
                if "pronunciation" in word and not is_text(word["pronunciation"], maximum=200):
                    problems.append(
                        f"{where}: vocabulary word {position + 1} pronunciation must be short text"
                    )
    if "sources" in entry:
        sources = entry["sources"]
        if not isinstance(sources, list):
            problems.append(f"{where}: entry.sources must be a list")
        elif len(sources) > 20:
            problems.append(f"{where}: entry.sources may hold at most 20 items")
        elif any(not is_text(source, maximum=2000) for source in sources):
            problems.append(f"{where}: entry.sources must only contain short text")
    if "relatedIds" in entry:
        related = entry["relatedIds"]
        if not isinstance(related, list):
            problems.append(f"{where}: entry.relatedIds must be a list")
        elif len(related) > 20:
            problems.append(f"{where}: entry.relatedIds may hold at most 20 items")
        elif any(not is_id(item) for item in related):
            problems.append(f"{where}: entry.relatedIds must only contain valid ids")
    if "extra" in entry:
        extra = entry["extra"]
        if not isinstance(extra, dict):
            problems.append(f"{where}: entry.extra must be an object")
        elif any(not isinstance(key, str) or len(key) > 60 for key in extra):
            problems.append(f"{where}: entry.extra must use short text field names")
    if "introduction" in entry and not is_text(entry["introduction"], maximum=1000):
        problems.append(f"{where}: entry.introduction must be short text")
    if "curiosityQuestion" in entry and not is_text(entry["curiosityQuestion"], maximum=1000):
        problems.append(f"{where}: entry.curiosityQuestion must be short text")
    if "grade1" in entry:
        grade = entry["grade1"]
        if not isinstance(grade, dict):
            problems.append(f"{where}: entry.grade1 must be an object")
        else:
            if not is_text(grade.get("body"), maximum=8000):
                problems.append(f"{where}: entry.grade1.body is required")
            kw = grade.get("keyWords", [])
            if not isinstance(kw, list) or len(kw) > 15:
                problems.append(f"{where}: entry.grade1.keyWords may hold at most 15 items")
            elif any(not is_text(item, maximum=60) for item in kw):
                problems.append(f"{where}: entry.grade1.keyWords must only contain short text")
    if "grade2" in entry:
        grade = entry["grade2"]
        if not isinstance(grade, dict):
            problems.append(f"{where}: entry.grade2 must be an object")
        else:
            if not is_text(grade.get("body"), maximum=8000):
                problems.append(f"{where}: entry.grade2.body is required")
            kw = grade.get("keyWords", [])
            if not isinstance(kw, list) or len(kw) > 15:
                problems.append(f"{where}: entry.grade2.keyWords may hold at most 15 items")
            elif any(not is_text(item, maximum=60) for item in kw):
                problems.append(f"{where}: entry.grade2.keyWords must only contain short text")
    if "sections" in entry:
        sections = entry["sections"]
        if not isinstance(sections, list):
            problems.append(f"{where}: entry.sections must be a list")
        elif len(sections) > MAX_SECTIONS:
            problems.append(f"{where}: entry.sections may hold at most {MAX_SECTIONS} items")
        else:
            for position, section in enumerate(sections):
                if not isinstance(section, dict):
                    problems.append(f"{where}: section {position + 1} must be an object")
                    continue
                s_where = f"{where}: section {position + 1}"
                for key in section:
                    if key not in {
                        "id", "title", "type", "grade", "paragraphs", "steps", "facts",
                        "examples", "vocabulary", "activity", "questionId", "curiosity",
                        "relatedIds", "imageIds", "diagrams",
                    }:
                        problems.append(f"{s_where}: unknown field '{key}'")
                if not is_id(section.get("id")):
                    problems.append(f"{s_where}: section.id is missing or invalid")
                if not is_text(section.get("title"), maximum=200):
                    problems.append(f"{s_where}: section.title is required")
                section_type = section.get("type")
                valid_types = {
                    "intro", "explanation", "steps", "facts", "examples",
                    "vocabulary", "activity", "quiz", "curiosity", "related",
                }
                if section_type not in valid_types:
                    problems.append(f"{s_where}: section.type must be one of {sorted(valid_types)}")
                grade_val = section.get("grade", "both")
                if grade_val not in ("1", "2", "both"):
                    problems.append(f"{s_where}: section.grade must be '1', '2' or 'both'")
                if "questionId" in section and not is_id(section["questionId"]):
                    problems.append(f"{s_where}: section.questionId is not a valid id")
                if "curiosity" in section and not is_text(section["curiosity"], maximum=1000):
                    problems.append(f"{s_where}: section.curiosity must be short text")
                for key in ("paragraphs", "examples"):
                    if key in section:
                        if not isinstance(section[key], list):
                            problems.append(f"{s_where}: section.{key} must be a list")
                        elif any(not is_text(item, maximum=500 if key == "examples" else 2000) for item in section[key]):
                            problems.append(f"{s_where}: section.{key} must only contain short text")
                if "steps" in section:
                    steps = section["steps"]
                    if not isinstance(steps, list):
                        problems.append(f"{s_where}: section.steps must be a list")
                    elif any(not is_text(item, maximum=1000) for item in steps):
                        problems.append(f"{s_where}: section.steps must only contain short text")
                if "facts" in section:
                    facts = section["facts"]
                    if not isinstance(facts, list):
                        problems.append(f"{s_where}: section.facts must be a list")
                    else:
                        for fact_pos, fact in enumerate(facts):
                            f_where = f"{s_where}: fact {fact_pos + 1}"
                            if not isinstance(fact, dict):
                                problems.append(f"{f_where}: must be an object")
                                continue
                            if not is_text(fact.get("title"), maximum=100):
                                problems.append(f"{f_where}: title is required")
                            if not is_text(fact.get("text"), maximum=500):
                                problems.append(f"{f_where}: text is required")
                            if "imageId" in fact and fact["imageId"] is not None and not is_id(fact["imageId"]):
                                problems.append(f"{f_where}: imageId is not a valid id")
                if "vocabulary" in section:
                    vocab = section["vocabulary"]
                    if not isinstance(vocab, list):
                        problems.append(f"{s_where}: section.vocabulary must be a list")
                    elif len(vocab) > 10:
                        problems.append(f"{s_where}: section.vocabulary may hold at most 10 items")
                    else:
                        for word_pos, word in enumerate(vocab):
                            w_where = f"{s_where}: vocabulary word {word_pos + 1}"
                            if not isinstance(word, dict):
                                problems.append(f"{w_where}: must be an object")
                                continue
                            if not is_text(word.get("term"), maximum=120):
                                problems.append(f"{w_where}: term is required")
                            if not is_text(word.get("definition"), maximum=600):
                                problems.append(f"{w_where}: definition is required")
                if "activity" in section:
                    activity = section["activity"]
                    if not isinstance(activity, dict):
                        problems.append(f"{s_where}: section.activity must be an object")
                    else:
                        a_where = f"{s_where}: activity"
                        if not is_text(activity.get("title"), maximum=200):
                            problems.append(f"{a_where}: title is required")
                        if not is_text(activity.get("description"), maximum=2000):
                            problems.append(f"{a_where}: description is required")
                        mats = activity.get("materials", [])
                        if not isinstance(mats, list):
                            problems.append(f"{a_where}: materials must be a list")
                        elif any(not is_text(item, maximum=100) for item in mats):
                            problems.append(f"{a_where}: materials must only contain short text")
                        acts = activity.get("steps", [])
                        if not isinstance(acts, list):
                            problems.append(f"{a_where}: steps must be a list")
                        elif any(not is_text(item, maximum=500) for item in acts):
                            problems.append(f"{a_where}: steps must only contain short text")
                        if "imageId" in activity and activity["imageId"] is not None and not is_id(activity["imageId"]):
                            problems.append(f"{a_where}: imageId is not a valid id")
                if "relatedIds" in section:
                    related = section["relatedIds"]
                    if not isinstance(related, list):
                        problems.append(f"{s_where}: section.relatedIds must be a list")
                    elif any(not is_id(item) for item in related):
                        problems.append(f"{s_where}: section.relatedIds must only contain valid ids")
                if "imageIds" in section:
                    img_ids = section["imageIds"]
                    if not isinstance(img_ids, list):
                        problems.append(f"{s_where}: section.imageIds must be a list")
                    elif any(not is_id(item) for item in img_ids):
                        problems.append(f"{s_where}: section.imageIds must only contain valid ids")
                if "diagrams" in section:
                    diagrams = section["diagrams"]
                    if not isinstance(diagrams, list):
                        problems.append(f"{s_where}: section.diagrams must be a list")
                    else:
                        for diag_pos, diagram in enumerate(diagrams):
                            d_where = f"{s_where}: diagram {diag_pos + 1}"
                            if not isinstance(diagram, dict):
                                problems.append(f"{d_where}: must be an object")
                                continue
                            if not is_id(diagram.get("id")):
                                problems.append(f"{d_where}: id is missing or invalid")
                            if not is_id(diagram.get("imageId")):
                                problems.append(f"{d_where}: imageId is not a valid id")
                            if "caption" in diagram and not is_text(diagram["caption"], maximum=500):
                                problems.append(f"{d_where}: caption must be short text")
                            labels = diagram.get("labels", [])
                            if not isinstance(labels, list):
                                problems.append(f"{d_where}: labels must be a list")
                            else:
                                for label_pos, label in enumerate(labels):
                                    l_where = f"{d_where}: label {label_pos + 1}"
                                    if not isinstance(label, dict):
                                        problems.append(f"{l_where}: must be an object")
                                        continue
                                    if not is_text(label.get("text"), maximum=200):
                                        problems.append(f"{l_where}: text is required")
                                    x = label.get("x")
                                    y = label.get("y")
                                    if not isinstance(x, (int, float)) or not 0 <= x <= 100:
                                        problems.append(f"{l_where}: x must be a number between 0 and 100")
                                    if not isinstance(y, (int, float)) or not 0 <= y <= 100:
                                        problems.append(f"{l_where}: y must be a number between 0 and 100")


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
        "pairs",
        "items",
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
    elif question_type == "matching":
        pairs = question.get("pairs")
        if not isinstance(pairs, list) or not 2 <= len(pairs) <= MAX_MATCHING_PAIRS:
            problems.append(f"{where}: question.pairs must hold 2 to {MAX_MATCHING_PAIRS} pairs")
        else:
            lefts: set[str] = set()
            rights: set[str] = set()
            for position, pair in enumerate(pairs):
                if not isinstance(pair, dict):
                    problems.append(f"{where}: pair {position + 1} must be an object")
                    continue
                for key in pair:
                    if key not in {"left", "right"}:
                        problems.append(f"{where}: pair {position + 1} has unknown field '{key}'")
                if not is_text(pair.get("left"), maximum=200):
                    problems.append(f"{where}: pair {position + 1} needs a left item")
                if not is_text(pair.get("right"), maximum=200):
                    problems.append(f"{where}: pair {position + 1} needs a right item")
                if pair.get("left") in lefts:
                    problems.append(f"{where}: pair {position + 1} repeats the left item")
                if pair.get("right") in rights:
                    problems.append(f"{where}: pair {position + 1} repeats the right item")
                lefts.add(pair.get("left"))
                rights.add(pair.get("right"))
    elif question_type == "ordering":
        items = question.get("items")
        if not isinstance(items, list) or not 2 <= len(items) <= MAX_ORDERING_ITEMS:
            problems.append(f"{where}: question.items must hold 2 to {MAX_ORDERING_ITEMS} items")
        else:
            for position, item in enumerate(items):
                if not is_text(item, maximum=200):
                    problems.append(f"{where}: item {position + 1} must be short text")


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

    # Related topics must exist inside the same pack (the app checks this too).
    for entry in entries:
        if isinstance(entry, dict):
            for related_id in entry.get("relatedIds", []) or []:
                if related_id not in entry_ids:
                    problems.append(
                        f"{source}: entry '{entry.get('id')}' links to unknown topic '{related_id}'"
                    )

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


def required_app_version(pack: Any) -> str | None:
    """The newest app version needed to read this pack, or None.

    A pack that only uses the original fields can be read by every app that
    has ever been published. A pack that uses the richer entry fields or a
    matching question needs a newer app, and the build refuses to publish it
    for an older one.
    """
    if not isinstance(pack, dict):
        return None

    entries = pack.get("entries") or []
    questions = pack.get("questions") or []

    uses_rich_entry = any(
        isinstance(entry, dict) and any(field in entry for field in RICH_ENTRY_FIELDS)
        for entry in entries
    )
    uses_matching = any(
        isinstance(question, dict) and question.get("type") == "matching"
        for question in questions
    )
    if uses_rich_entry or uses_matching:
        return APP_VERSION_WITH_RICH_FIELDS
    return None


def compare_versions(left: str, right: str) -> int:
    """Compare two dotted version strings. Returns -1, 0 or 1."""
    left_parts = [int(part) for part in left.split(".") if part.isdigit()]
    right_parts = [int(part) for part in right.split(".") if part.isdigit()]
    length = max(len(left_parts), len(right_parts))
    for index in range(length):
        a = left_parts[index] if index < len(left_parts) else 0
        b = right_parts[index] if index < len(right_parts) else 0
        if a > b:
            return 1
        if a < b:
            return -1
    return 0


def validate_image_files(pack: Any, content_dir: str, *, source: str = "<pack>") -> list[str]:
    """Check that every declared picture exists and carries its licence details."""
    problems: list[str] = []
    if not isinstance(pack, dict):
        return problems

    assets = pack.get("assets") or []
    attributions = pack.get("attributions") or {}

    for index, asset in enumerate(assets):
        where = f"{source}: asset {index}"
        if not isinstance(asset, dict):
            continue
        asset_id = asset.get("id")
        for key in ("full", "thumb"):
            relative = asset.get(key)
            if not isinstance(relative, str) or not relative:
                continue
            path = os.path.join(content_dir, relative)
            if not os.path.exists(path):
                problems.append(f"{where}: picture file is missing: {relative}")
            elif os.path.getsize(path) == 0:
                problems.append(f"{where}: picture file is empty: {relative}")
        if isinstance(asset_id, str) and asset_id not in attributions:
            problems.append(f"{where}: picture '{asset_id}' has no licence details")

    for asset_id in attributions:
        if not any(
            isinstance(asset, dict) and asset.get("id") == asset_id for asset in assets
        ):
            problems.append(
                f"{source}: licence details for '{asset_id}' do not belong to any picture"
            )

    return problems


def validate_library(packs: list[dict], *, content_dir: str | None = None) -> list[str]:
    """Check the library as a whole, not one pack at a time.

    The library is what the application downloads, so problems that only show
    up between packs (a duplicated pack id, a picture used by two packs with
    different licences) are found here.
    """
    problems: list[str] = []
    seen_pack_ids: dict[str, int] = {}
    attribution_by_path: dict[str, tuple[str, dict]] = {}

    for index, pack in enumerate(packs):
        if not isinstance(pack, dict):
            continue
        pack_id = pack.get("packId")
        if not isinstance(pack_id, str):
            continue
        if pack_id in seen_pack_ids:
            problems.append(
                f"library: pack id '{pack_id}' is used by more than one pack file"
            )
        seen_pack_ids[pack_id] = index

        if content_dir is not None:
            problems.extend(validate_image_files(pack, content_dir, source=f"pack '{pack_id}'"))

        assets = pack.get("assets") or []
        attributions = pack.get("attributions") or {}
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            asset_id = asset.get("id")
            attribution = attributions.get(asset_id) if isinstance(asset_id, str) else None
            if not isinstance(attribution, dict):
                continue
            for key in ("full", "thumb"):
                relative = asset.get(key)
                if not isinstance(relative, str) or not relative:
                    continue
                previous = attribution_by_path.get(relative)
                if previous is None:
                    attribution_by_path[relative] = (pack_id, attribution)
                elif previous[1] != attribution:
                    problems.append(
                        f"library: picture '{relative}' has different licence details in "
                        f"'{previous[0]}' and '{pack_id}'"
                    )

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
