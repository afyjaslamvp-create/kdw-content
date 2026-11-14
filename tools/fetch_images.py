"""Fetch images for the content library from Wikimedia Commons.

Images are downloaded once, at authoring time, and stored in the repository.
The application never asks a third party for a picture at runtime, so the
content keeps working offline and no external host can break a lesson.

    python tools/fetch_images.py --all
    python tools/fetch_images.py --only lion tiger

Licences that are accepted are limited to public domain and Creative Commons
share-alike style licences. Every picture keeps its source link, creator and
licence name in `content/attributions.json` and inside the pack that uses it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from content_lib import read_json, write_json  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is required for image work
    print("Pillow is required: pip install Pillow", file=sys.stderr)
    raise

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENT_DIR = os.path.join(ROOT, "content")
IMAGES_DIR = os.path.join(CONTENT_DIR, "images")
SOURCES_FILE = os.path.join(CONTENT_DIR, "image-sources.json")
ATTRIBUTIONS_FILE = os.path.join(CONTENT_DIR, "attributions.json")

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks every tool to identify itself with a contact address.
USER_AGENT = (
    "KidsDiscoveryWorldContentBuilder/1.0 "
    "(educational image library for Kids Discovery World; "
    "contact: set-your-email@example.org)"
)

# Be gentle with the Wikimedia API: one request at a time with a pause, and
# honour the Retry-After header when the server asks us to slow down.
REQUEST_PAUSE_SECONDS = 1.5
DOWNLOAD_PAUSE_SECONDS = 0.4
MAX_ATTEMPTS = 5

FULL_WIDTH = 1280
THUMB_WIDTH = 320
WEBP_QUALITY = 78
THUMB_QUALITY = 72

# Only these licences are accepted.
ALLOWED_LICENCE_PATTERNS = (
    "public domain",
    "cc0",
    "cc by 2.0",
    "cc by 3.0",
    "cc by 4.0",
    "cc by-sa 2.0",
    "cc by-sa 3.0",
    "cc by-sa 4.0",
    "attribution",
    "no restrictions",
)


class FetchError(Exception):
    pass


def _request(url: str, timeout: int) -> bytes:
    """Fetch a URL, backing off when the server says we are going too fast."""
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 429 or error.code >= 500:
                retry_after = error.headers.get("Retry-After") if error.headers else None
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 5.0 * (2**attempt)
                print(f"    server asked us to slow down, waiting {delay:.0f}s")
                time.sleep(delay)
                continue
            raise
        except urllib.error.URLError as error:
            last_error = error
            time.sleep(3.0 * (attempt + 1))
    raise FetchError(f"could not reach {url}: {last_error}")


def api_get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    payload = _request(url, timeout=30)
    time.sleep(REQUEST_PAUSE_SECONDS)
    return json.loads(payload.decode("utf-8"))


def search_with_info(term: str, limit: int = 20) -> list[tuple[str, dict]]:
    """Search for files and get their licence information in one request."""
    data = api_get(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{term} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": str(limit),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": str(FULL_WIDTH),
        }
    )
    pages = data.get("query", {}).get("pages", {})
    results: list[tuple[str, dict]] = []
    for page in pages.values():
        info = page.get("imageinfo")
        if info:
            results.append((page.get("title", ""), info[0]))
    return results


def search_files(term: str, limit: int = 8) -> list[str]:
    data = api_get(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": f"{term} filetype:bitmap",
            "srnamespace": "6",
            "srlimit": str(limit),
        }
    )
    return [item["title"] for item in data.get("query", {}).get("search", [])]


def image_info(title: str) -> dict | None:
    data = api_get(
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": str(FULL_WIDTH),
        }
    )
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = page.get("imageinfo")
        if info:
            return info[0]
    return None


def licence_is_allowed(licence: str) -> bool:
    lowered = licence.lower()
    return any(pattern in lowered for pattern in ALLOWED_LICENCE_PATTERNS)


def clean_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", value or "").strip()


def display_title(file_title: str) -> str:
    """Turn a Commons file name into a short, readable title."""
    import re

    name = file_title.split(":", 1)[-1] if ":" in file_title else file_title
    name = re.sub(r"\.(jpe?g|png|webp|gif|tiff?|svg)$", "", name, flags=re.IGNORECASE)
    name = name.replace("_", " ").strip()
    return name[:300] or "Picture"


def build_attribution(meta: dict, file_title: str = "") -> dict:
    def field(name: str) -> str:
        raw = meta.get(name, {}).get("value", "")
        return clean_html(str(raw))

    licence = field("LicenseShortName") or field("UsageTerms") or "Unknown"
    artist = field("Artist") or field("Credit") or "Unknown"
    # The Commons page address is built from the file name, which is always
    # available and always correct.
    source = (
        "https://commons.wikimedia.org/wiki/"
        + urllib.parse.quote(file_title.replace(" ", "_"), safe=":/(),!'")
        if file_title
        else field("CanonicalURL")
    )
    attribution = {
        "title": display_title(file_title),
        "creator": artist[:300],
        "license": licence[:120],
        "sourceUrl": source,
        "attributionRequired": True,
    }
    # Optional fields are only included when they hold a real value, so the
    # application never sees an empty URL.
    for key in ("licenseUrl", "creatorUrl"):
        value = field(key)
        if value:
            attribution[key] = value
    return attribution


def download(url: str) -> bytes:
    payload = _request(url, timeout=60)
    time.sleep(DOWNLOAD_PAUSE_SECONDS)
    return payload


def to_webp(raw: bytes, width: int, quality: int) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=quality, method=6)
    return buffer.getvalue()


def pick_image(entry: dict) -> dict:
    """Find an allowed, suitable picture for one image id."""
    if entry.get("commons"):
        info = image_info(entry["commons"])
        candidates = [(entry["commons"], info)] if info else []
    else:
        candidates = search_with_info(entry["search"], limit=int(entry.get("limit", 20)))

    for title, info in candidates:
        if not info:
            continue
        meta = info.get("extmetadata", {})
        licence = clean_html(str(meta.get("LicenseShortName", {}).get("value", "")))
        if not licence_is_allowed(licence):
            print(f"    skipped {title}: licence '{licence}' is not allowed")
            continue
        mime = info.get("mime", "")
        if not mime.startswith("image/") or mime == "image/svg+xml":
            print(f"    skipped {title}: not a usable bitmap ({mime})")
            continue
        url = info.get("thumburl") or info.get("url")
        if not url:
            continue
        return {"title": title, "url": url, "meta": meta}

    raise FetchError(f"no allowed image found for '{entry.get('id')}'")


def file_title_from_source(source_url: str) -> str:
    """Recover the Commons file name from the stored source link."""
    if "commons.wikimedia.org/wiki/" not in source_url:
        return ""
    tail = source_url.split("commons.wikimedia.org/wiki/", 1)[1]
    return urllib.parse.unquote(tail.split("#")[0]).replace("_", " ")


def refresh_attribution(entry: dict, cached: dict) -> dict | None:
    """Re-read the licence details for a picture that is already on disk."""
    title = file_title_from_source(cached.get("sourceUrl", ""))
    if not title:
        return None
    info = image_info(title)
    if not info:
        return None
    meta = info.get("extmetadata", {})
    licence = clean_html(str(meta.get("LicenseShortName", {}).get("value", "")))
    if not licence_is_allowed(licence):
        print(f"    licence for {title} is now '{licence}', keeping the old entry")
        return None
    return {"id": entry["id"], **build_attribution(meta, title)}


def fetch_one(entry: dict, force: bool = False, known: dict | None = None) -> dict | None:
    image_id = entry["id"]
    full_path = os.path.join(IMAGES_DIR, f"{image_id}.webp")
    thumb_path = os.path.join(IMAGES_DIR, f"{image_id}.thumb.webp")
    if os.path.exists(full_path) and os.path.exists(thumb_path) and not force:
        cached = (known or {}).get(image_id)
        if cached:
            print(f"  {image_id}: already downloaded")
            return {"id": image_id, **cached}
        # The picture is on disk but its licence details were never written.
        # Download it again so the attribution is captured.
        print(f"  {image_id}: licence details missing, fetching again")
    else:
        print(f"  {image_id}: looking for a picture...")

    chosen = pick_image(entry)
    raw = download(chosen["url"])
    full = to_webp(raw, FULL_WIDTH, WEBP_QUALITY)
    thumb = to_webp(raw, THUMB_WIDTH, THUMB_QUALITY)

    os.makedirs(IMAGES_DIR, exist_ok=True)
    with open(full_path, "wb") as handle:
        handle.write(full)
    with open(thumb_path, "wb") as handle:
        handle.write(thumb)

    attribution = build_attribution(chosen["meta"], chosen["title"])
    attribution["sourceUrl"] = attribution["sourceUrl"] or (
        "https://commons.wikimedia.org/wiki/"
        + urllib.parse.quote(chosen["title"].replace(" ", "_"))
    )
    if not attribution.get("licenseUrl"):
        attribution["licenseUrl"] = "https://creativecommons.org/licenses/by-sa/4.0/"
    print(
        f"  {image_id}: {len(full) // 1024} KB full, {len(thumb) // 1024} KB thumb "
        f"({attribution['license']})"
    )
    return {"id": image_id, **attribution}


def update_attributions(entries: list[dict]) -> dict:
    """Merge the given attributions into content/attributions.json."""
    data = {}
    if os.path.exists(ATTRIBUTIONS_FILE):
        data = read_json(ATTRIBUTIONS_FILE)
    for entry in entries:
        data[entry["id"]] = {key: value for key, value in entry.items() if key != "id"}
    write_json(ATTRIBUTIONS_FILE, data)
    return data


def patch_packs(attributions: dict) -> None:
    """Copy the attribution into every pack that uses the picture."""
    from content_lib import find_pack_files

    for path in find_pack_files(CONTENT_DIR):
        pack = read_json(path)
        changed = False
        assets = pack.get("assets", [])
        for asset in assets:
            full = asset.get("full", "")
            if not full.startswith("images/"):
                continue
            image_id = os.path.basename(full).rsplit(".", 1)[0]
            if image_id in attributions:
                pack.setdefault("attributions", {})[image_id] = attributions[image_id]
                changed = True
        if changed:
            write_json(path, pack)
            print(f"  updated {os.path.relpath(path, CONTENT_DIR)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download pictures from Wikimedia Commons.")
    parser.add_argument("--all", action="store_true", help="Fetch every picture in the list.")
    parser.add_argument("--only", nargs="*", help="Fetch only these image ids.")
    parser.add_argument("--force", action="store_true", help="Download again even if it exists.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-read the licence details for pictures that are already downloaded.",
    )
    args = parser.parse_args()

    if not os.path.exists(SOURCES_FILE):
        print(f"No image list found at {SOURCES_FILE}", file=sys.stderr)
        return 1

    sources = read_json(SOURCES_FILE)
    wanted = sources
    if args.only:
        wanted = [entry for entry in sources if entry["id"] in set(args.only)]
    if not args.all and not args.only:
        print("Use --all or --only <ids>.", file=sys.stderr)
        return 1

    known = {}
    if os.path.exists(ATTRIBUTIONS_FILE):
        known = read_json(ATTRIBUTIONS_FILE)

    collected: list[dict] = []
    failures: list[str] = []

    for entry in wanted:
        try:
            if args.refresh:
                cached = known.get(entry["id"])
                if cached and os.path.exists(os.path.join(IMAGES_DIR, f"{entry['id']}.webp")):
                    refreshed = refresh_attribution(entry, cached)
                    if refreshed:
                        collected.append(refreshed)
                        print(f"  {entry['id']}: licence details refreshed")
                    continue
            result = fetch_one(entry, force=args.force, known=known)
            if result:
                collected.append(result)
        except FetchError as error:
            print(f"  FAILED: {error}", file=sys.stderr)
            failures.append(entry["id"])
        except Exception as error:  # network problems and so on
            print(f"  FAILED: {error}", file=sys.stderr)
            failures.append(entry["id"])
        time.sleep(0.8)  # be polite to the Wikimedia API

    # The packs are patched with the complete set of attributions, not only the
    # ones fetched in this run, so a resumed run still ends up complete.
    merged = update_attributions(collected)
    patch_packs(merged)

    print()
    if failures:
        print(f"{len(failures)} picture(s) could not be fetched: {', '.join(failures)}")
        return 1
    print("All requested pictures are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
