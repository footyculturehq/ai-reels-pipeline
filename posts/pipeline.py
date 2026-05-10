"""
Footy Culture HQ — Automated Instagram Posting Pipeline
--------------------------------------------------------
Runs 3x/day via GitHub Actions (8am, 2pm, 8pm UTC).

Flow:
  1. Scrape footyheadlines.com for boot/kit news ≤ 3 days old
  2. Skip stories already in posted_stories.json
  3. Pick the freshest unposted story
  4. Find a portrait image via Google Custom Search, fallback to Pexels
  5. Generate a 1080×1440 post card using create_post.py
  6. Post the image directly to Instagram via instagrapi
  7. Append story to posted_stories.json and commit (done by GitHub Actions)

Required GitHub Secrets:
  INSTAGRAM_USERNAME  — e.g. footyculturehq
  INSTAGRAM_PASSWORD  — Instagram account password
  GOOGLE_API_KEY      — Google Custom Search API key
  PEXELS_API_KEY      — Pexels API key
"""

import io
import json
import logging
import os
import re
import sys
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
POSTED_FILE = SCRIPT_DIR / "posted_stories.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FOOTY_HEADLINES_URL = "https://www.footyheadlines.com"
MAX_AGE_DAYS = 3

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CX = "017576662512468239146:omuauf_lfve"
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

INSTAGRAM_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.environ.get("INSTAGRAM_PASSWORD", "")
INSTAGRAM_SESSION_FILE = SCRIPT_DIR / "instagram_session.json"

# Request headers — look like a real browser to avoid 403s
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_posted() -> list[dict]:
    if POSTED_FILE.exists():
        try:
            return json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        except Exception:
            log.warning("Could not parse posted_stories.json — starting fresh.")
    return []


def _save_posted(posted: list[dict]) -> None:
    POSTED_FILE.write_text(
        json.dumps(posted, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _already_posted(story_id: str, posted: list[dict]) -> bool:
    return any(p.get("id") == story_id for p in posted)


def _story_id(title: str) -> str:
    """Stable identifier: lowercase slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:120]


# ---------------------------------------------------------------------------
# 1. Scrape footyheadlines.com
# ---------------------------------------------------------------------------

def scrape_stories(max_age_days: int = MAX_AGE_DAYS) -> list[dict]:
    """
    Returns a list of dicts sorted newest-first:
      {id, title, url, date, age_days}
    """
    log.info("Scraping %s …", FOOTY_HEADLINES_URL)
    try:
        resp = requests.get(FOOTY_HEADLINES_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.error("Failed to fetch footyheadlines.com: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    now = datetime.now(tz=timezone.utc)
    stories: list[dict] = []

    # footyheadlines.com uses <article> or <div class="post"> blocks.
    # Each block has an <a> with the headline and optionally a <time> or date
    # in a <span class="meta-date"> / <span class="date"> element.
    # We try multiple selectors for robustness.
    candidates = soup.select("article") or soup.select(".post")

    for block in candidates:
        # ── Title & URL ──────────────────────────────────────────────────────
        link_tag = block.find("a", href=True)
        if not link_tag:
            continue
        title = link_tag.get_text(separator=" ", strip=True)
        if not title or len(title) < 10:
            # try <h2> or <h3> inside the block
            for hx in block.find_all(["h2", "h3", "h4"]):
                t = hx.get_text(separator=" ", strip=True)
                if len(t) >= 10:
                    title = t
                    break
        href = link_tag["href"]
        if not href.startswith("http"):
            href = FOOTY_HEADLINES_URL.rstrip("/") + "/" + href.lstrip("/")

        # ── Date ─────────────────────────────────────────────────────────────
        story_date: datetime | None = None

        # Strategy A: <time datetime="…">
        time_tag = block.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                raw = time_tag["datetime"][:19]  # "2025-04-30T14:00:00"
                story_date = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Strategy B: visible date text in known class names
        if story_date is None:
            for cls in ("meta-date", "date", "post-date", "entry-date", "published"):
                span = block.find(class_=cls)
                if span:
                    raw_text = span.get_text(strip=True)
                    story_date = _parse_date_text(raw_text, now)
                    if story_date:
                        break

        # Strategy C: any text that looks like "Apr 30, 2025" or "30 Apr 2025"
        if story_date is None:
            story_date = _parse_date_text(block.get_text(" ", strip=True), now)

        # If we still have no date, assume it's recent (today) to not miss content
        if story_date is None:
            story_date = now

        age_days = (now - story_date).days
        if age_days > max_age_days:
            continue  # too old

        sid = _story_id(title)
        stories.append({
            "id": sid,
            "title": title,
            "url": href,
            "date": story_date.isoformat(),
            "age_days": age_days,
        })

    # De-duplicate by id, keep newest
    seen: set[str] = set()
    unique: list[dict] = []
    for s in stories:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    unique.sort(key=lambda x: x["age_days"])  # freshest first
    log.info("Found %d stories ≤ %d days old.", len(unique), max_age_days)
    return unique


def _parse_date_text(text: str, now: datetime) -> "datetime | None":
    """Attempt to parse common date formats from a string. Returns UTC datetime or None."""
    # Relative: "2 days ago", "1 hour ago", "3 hours ago", "yesterday"
    text_l = text.lower()
    m = re.search(r"(\d+)\s+hour[s]?\s+ago", text_l)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    m = re.search(r"(\d+)\s+day[s]?\s+ago", text_l)
    if m:
        return now - timedelta(days=int(m.group(1)))
    if "yesterday" in text_l:
        return now - timedelta(days=1)
    if "today" in text_l or "just now" in text_l or "moments ago" in text_l:
        return now

    # Absolute: "April 30, 2025" / "Apr 30, 2025" / "30 Apr 2025" / "2025-04-30"
    month_names = (
        "january|february|march|april|may|june|july|august|september|"
        "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec"
    )
    patterns = [
        r"(\d{4})-(\d{2})-(\d{2})",                                   # ISO
        rf"({month_names})\s+(\d{{1,2}}),?\s+(\d{{4}})",              # Apr 30, 2025
        rf"(\d{{1,2}})\s+({month_names})\s+(\d{{4}})",                # 30 Apr 2025
    ]
    for pat in patterns:
        m = re.search(pat, text_l)
        if m:
            try:
                groups = m.groups()
                if "-" in pat:
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif pat.startswith(rf"({month_names})"):
                    mo = _month_num(groups[0])
                    d  = int(groups[1])
                    y  = int(groups[2])
                else:
                    d  = int(groups[0])
                    mo = _month_num(groups[1])
                    y  = int(groups[2])
                return datetime(y, mo, d, tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _month_num(name: str) -> int:
    months = {
        "january": 1, "jan": 1, "february": 2, "feb": 2,
        "march": 3, "mar": 3, "april": 4, "apr": 4,
        "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sep": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }
    return months.get(name.lower().strip(), 1)


# ---------------------------------------------------------------------------
# 2. Choose tag based on story content
# ---------------------------------------------------------------------------
_TAG_KEYWORDS: list[tuple[str, list[str]]] = [
    ("BREAKING", ["breaking", "confirmed", "official", "announced"]),
    ("DROPPED",  ["release", "drop", "launch", "on sale", "available now", "buy now"]),
    ("SPOTTED",  ["spotted", "leaked", "training", "match worn", "worn by"]),
    ("NEWS",     []),  # default
]


def pick_tag(title: str) -> str:
    tl = title.lower()
    for tag, keywords in _TAG_KEYWORDS:
        if any(kw in tl for kw in keywords):
            return tag
    return "NEWS"


# ---------------------------------------------------------------------------
# 3. Format headline for the template
# ---------------------------------------------------------------------------

def format_headline(title: str) -> str:
    """
    Clean up the raw article title for the visual template.
    - Strip site name suffix (e.g. "— Footy Headlines")
    - Capitalise properly
    - Trim to a sensible length for the card
    """
    # Remove site suffix patterns
    title = re.sub(r"\s*[|—–-]\s*(footy headlines?|footyheadlines\.com).*$",
                   "", title, flags=re.IGNORECASE).strip()
    # Sentence-case (keep existing caps for brand names)
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
    # Hard cap at 80 chars so it fits on the card
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0] + "…"
    return title


# ---------------------------------------------------------------------------
# 4. Build Instagram caption
# ---------------------------------------------------------------------------

def build_caption(title: str, tag: str) -> str:
    """3-4 hashtags relevant to the story + the handle."""
    title_l = title.lower()

    tags: list[str] = []

    # Brand hashtags
    brand_map = {
        "nike": "#Nike",
        "adidas": "#Adidas",
        "puma": "#Puma",
        "new balance": "#NewBalance",
        "mizuno": "#Mizuno",
        "umbro": "#Umbro",
        "under armour": "#UnderArmour",
    }
    for brand, ht in brand_map.items():
        if brand in title_l:
            tags.append(ht)
            break

    # Topic hashtags
    topic_map = {
        "boot": "#FootballBoots",
        "cleat": "#FootballBoots",
        "kit": "#FootballKit",
        "jersey": "#FootballKit",
        "shirt": "#FootballKit",
        "goalkeeper": "#GoalkeeperKit",
    }
    for kw, ht in topic_map.items():
        if kw in title_l:
            tags.append(ht)
            break

    # Always include these core tags
    tags.append("#FootyCultureHQ")
    tags.append("#FootballNews")

    # Add a tag-specific hashtag
    tag_ht = {
        "BREAKING": "#BreakingNews",
        "DROPPED": "#JustDropped",
        "SPOTTED": "#FootballLeaks",
        "NEWS": "#FootballTransfers",
    }
    tags.append(tag_ht.get(tag, "#Football"))

    # Deduplicate while preserving order, limit to 5
    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)
    unique_tags = unique_tags[:5]

    return " ".join(unique_tags)


# ---------------------------------------------------------------------------
# 5a. Google Custom Search for portrait image
# ---------------------------------------------------------------------------

def _is_portrait(img_bytes: bytes) -> bool:
    """Return True if the image is portrait-oriented (height > width)."""
    try:
        img = Image.open(io.BytesIO(img_bytes))
        return img.height > img.width
    except Exception:
        return False


def _download_image(url: str, timeout: int = 15) -> "bytes | None":
    """Download image bytes; return None on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()
        content = resp.content
        if len(content) < 5000:  # too small to be a real image
            return None
        return content
    except Exception as exc:
        log.debug("Could not download %s: %s", url, exc)
        return None


def search_google_image(query: str) -> "bytes | None":
    """
    Search Google Custom Search for a portrait photo.
    Returns raw image bytes or None.
    """
    if not GOOGLE_API_KEY:
        log.warning("GOOGLE_API_KEY not set — skipping Google image search.")
        return None

    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "searchType": "image",
        "q": query,
        "imgType": "photo",
        "imgSize": "large",
        "num": 5,
        "safe": "active",
    }
    log.info("Google image search: %r", query)
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Google image search failed: %s", exc)
        return None

    items = data.get("items", [])
    if not items:
        log.info("Google returned 0 image results for %r.", query)
        return None

    for item in items:
        img_url = item.get("link", "")
        if not img_url:
            continue
        log.info("Trying Google image: %s", img_url)
        img_bytes = _download_image(img_url)
        if img_bytes and _is_portrait(img_bytes):
            log.info("Portrait image found via Google: %s", img_url)
            return img_bytes
        elif img_bytes:
            log.debug("Skipping landscape/square image: %s", img_url)

    return None


# ---------------------------------------------------------------------------
# 5b. Pexels fallback
# ---------------------------------------------------------------------------

def search_pexels_image(query: str) -> "bytes | None":
    """
    Search Pexels for a portrait photo.
    Returns raw image bytes or None.
    """
    if not PEXELS_API_KEY:
        log.warning("PEXELS_API_KEY not set — skipping Pexels search.")
        return None

    log.info("Pexels fallback search: %r", query)
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": 10, "orientation": "portrait"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Pexels search failed: %s", exc)
        return None

    photos = data.get("photos", [])
    if not photos:
        log.info("Pexels returned 0 results for %r.", query)
        return None

    for photo in photos:
        img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not img_url:
            continue
        log.info("Trying Pexels image: %s", img_url)
        img_bytes = _download_image(img_url)
        if img_bytes and _is_portrait(img_bytes):
            log.info("Portrait image found via Pexels: %s", img_url)
            return img_bytes

    return None


def find_image(title: str) -> "bytes | None":
    """
    Try Google first, Pexels second.
    Query is title + 'football boot' to keep results product-focused.
    """
    base_query = re.sub(r"\s*[|—–-].*$", "", title).strip()
    query = f"{base_query} football boot"

    img = search_google_image(query)
    if img:
        return img

    img = search_pexels_image(query)
    if img:
        return img

    # Last resort: generic "football boot" to at least have an image
    log.warning("No specific image found. Trying generic 'football boot' query.")
    img = search_google_image("football boot new release")
    if img:
        return img
    img = search_pexels_image("football boot")
    return img


# ---------------------------------------------------------------------------
# 6. Generate post image
# ---------------------------------------------------------------------------

def generate_post_image(
    headline: str,
    caption: str,
    image_path: "str | None",
    tag: str,
) -> "str | None":
    """
    Calls create_post.create_post() and returns the output PNG path.
    Returns None on failure.
    """
    try:
        # Import here so pipeline errors don't propagate during import
        sys.path.insert(0, str(SCRIPT_DIR))
        from create_post import create_post  # noqa: PLC0415

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(OUTPUT_DIR / f"post_{ts}.png")

        create_post(
            headline=headline,
            caption=caption,
            image_path=image_path,
            tag=tag,
            size="portrait",
            output_path=out_path,
            focal_point="center",
            fit=False,
        )
        return out_path
    except Exception as exc:
        log.error("create_post failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 7. Post to Instagram via instagrapi
# ---------------------------------------------------------------------------

def post_to_instagram(image_path: str, caption: str) -> bool:
    """
    Post image directly to Instagram using instagrapi.
    Uses a session file for persistence to avoid repeated logins.
    Returns True on success.
    """
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        log.error("INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD not set in environment.")
        return False

    try:
        from instagrapi import Client  # noqa: PLC0415
        from instagrapi.exceptions import LoginRequired  # noqa: PLC0415
    except ImportError:
        log.error("instagrapi is not installed. Add it to requirements.")
        return False

    cl = Client()
    # Mimic a real device to reduce bot-detection risk
    cl.set_locale("en_US")
    cl.set_timezone_offset(0)

    # Try loading existing session first
    session_loaded = False
    if INSTAGRAM_SESSION_FILE.exists():
        try:
            cl.load_settings(str(INSTAGRAM_SESSION_FILE))
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            cl.get_timeline_feed()  # test the session is alive
            session_loaded = True
            log.info("Reused existing Instagram session.")
        except (LoginRequired, Exception) as exc:
            log.warning("Existing session invalid (%s), re-logging in.", exc)
            cl = Client()
            cl.set_locale("en_US")
            cl.set_timezone_offset(0)
            session_loaded = False

    if not session_loaded:
        log.info("Logging into Instagram as @%s …", INSTAGRAM_USERNAME)
        try:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            log.info("Login successful.")
        except Exception as exc:
            log.error("Instagram login failed: %s", exc)
            return False

    # Save updated session for next run
    try:
        cl.dump_settings(str(INSTAGRAM_SESSION_FILE))
        log.info("Session saved to %s", INSTAGRAM_SESSION_FILE)
    except Exception as exc:
        log.warning("Could not save session: %s", exc)

    # Upload the post
    log.info("Uploading photo to Instagram …")
    try:
        media = cl.photo_upload(
            path=image_path,
            caption=caption,
        )
        log.info("Posted! Media ID: %s  URL: https://www.instagram.com/p/%s/",
                 media.pk, media.code)
        return True
    except Exception as exc:
        log.error("Instagram photo upload failed: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== Footy Culture HQ pipeline starting ===")

    # ── Load history ─────────────────────────────────────────────────────────
    posted = _load_posted()
    log.info("Stories already posted: %d", len(posted))

    # ── Scrape ───────────────────────────────────────────────────────────────
    stories = scrape_stories()
    if not stories:
        log.warning("No stories found. Exiting without posting.")
        return

    # ── Pick first unposted story ─────────────────────────────────────────────
    story = None
    for s in stories:
        if not _already_posted(s["id"], posted):
            story = s
            break

    if story is None:
        log.info("All recent stories have already been posted. Nothing to do.")
        return

    log.info("Selected story: %r (age %d days)", story["title"], story["age_days"])

    # ── Prepare content ──────────────────────────────────────────────────────
    tag = pick_tag(story["title"])
    headline = format_headline(story["title"])
    caption = build_caption(story["title"], tag)

    log.info("Tag: %s | Headline: %r", tag, headline)
    log.info("Caption: %s", caption)

    # ── Find image ────────────────────────────────────────────────────────────
    img_bytes = find_image(story["title"])
    tmp_img_path: "str | None" = None

    if img_bytes:
        # Save to a temp file that create_post.py can open
        with tempfile.NamedTemporaryFile(
            suffix=".jpg", delete=False, dir=str(OUTPUT_DIR)
        ) as tmp:
            tmp.write(img_bytes)
            tmp_img_path = tmp.name
        log.info("Downloaded image saved to: %s", tmp_img_path)
    else:
        log.warning("No image found — will generate post with no background photo.")

    # ── Generate post card ────────────────────────────────────────────────────
    post_path = generate_post_image(headline, caption, tmp_img_path, tag)

    # Clean up temp image
    if tmp_img_path and os.path.exists(tmp_img_path):
        try:
            os.unlink(tmp_img_path)
        except Exception:
            pass

    if not post_path:
        log.error("Image generation failed. Aborting.")
        return

    log.info("Post image: %s", post_path)

    # ── Post to Instagram directly ────────────────────────────────────────────
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        log.warning("INSTAGRAM_USERNAME/PASSWORD not set — skipping Instagram post.")
    else:
        success = post_to_instagram(post_path, caption)
        if not success:
            log.error("Instagram post failed. Not marking story as posted.")
            return

    # ── Record success ────────────────────────────────────────────────────────
    posted.append({
        "id": story["id"],
        "title": story["title"],
        "url": story["url"],
        "posted_at": datetime.now(tz=timezone.utc).isoformat(),
        "tag": tag,
    })
    _save_posted(posted)
    log.info("Marked %r as posted. Total posted: %d", story["id"], len(posted))
    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
