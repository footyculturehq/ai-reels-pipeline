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

# ── Nitter instances (tried in order; first live one wins) ───────────────────
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.mint.lgbt",
    "https://lightbird.cc",
]

# Twitter/X accounts to monitor — focused on LEAK & SPOTTER community,
# NOT official brand accounts (they post marketing, not early gossip).
# These accounts specialise in: athletes caught in unreleased boots at
# training/warm-ups, leaked colorways, rumoured releases, sample boots.
TWITTER_ACCOUNTS = [
    # ── Tier 1: Dedicated boot & kit leak accounts ───────────────────────────
    "footyheadlines",   # #1 boot leak source — renders, training spots, rumours
    "Kitboys_",         # kit / jersey leaks before official reveal
    "soccerbible",      # boot & kit culture, first-looks, exclusives
    "thebootroom",      # boot news, early reviews, leaked colourways
    "Footy_Boots",      # footy-boots.com — early hands-on & training spots
    # ── Tier 2: Spotter / community accounts ────────────────────────────────
    "footballboots",    # boots community — spotted in training & matches
    "BootsOnPitch",     # boots spotted being worn on pitch before release
    "UltraBoot",        # boot hype, leaks, unreleased samples
    "soccercleats101",  # cleat news, leaks, rumours (US angle)
    "KleanBoots",       # boots culture, spotted colourways
    "thebootologist",   # deep-dive boot analysis and leaked info
    "SoccerCleats",     # cleat leaks and early release info
]

# Keywords to keep a tweet relevant — heavy on LEAK / SPOTTER language.
# At least one must match (case-insensitive) for the tweet to be included.
BOOT_TWEET_KEYWORDS = [
    # ── Leak / gossip / hype verbs ────────────────────────────────────────────
    "spotted", "leaked", "leak", "exclusive", "first look", "first-look",
    "unreleased", "prototype", "sample", "unboxing",
    "rumoured", "rumored", "rumour", "rumor",
    "coming soon", "dropping", "drop", "upcoming",
    "revealed", "reveal", "confirmed", "breaking",
    "training", "training ground", "warm-up", "warmup", "warm up",
    "match worn", "game worn", "worn by", "wearing",
    "release", "colourway", "colorway", "collab", "collaboration",
    "player edition", "pe boot", "limited edition", "special edition",
    # ── Product types ────────────────────────────────────────────────────────
    "boot", "boots", "cleat", "cleats",
    "kit", "kits", "jersey", "shirt", "strip",
    # ── Specific boot models (catches model leaks even without 'boot') ────────
    "mercurial", "predator", "phantom", "tiempo", "superfly",
    "copa", "nemeziz", "x speedflow", "speedportal", "f50",
    "future", "ultra", "king", "evospeed", "tekela",
    "supercharge", "360", "trx", "icon",
    # ── Brands (catches brand mention even without product word) ─────────────
    "adidas", "nike", "puma", "new balance", "umbro", "mizuno",
    "hummel", "castore", "macron", "asics", "lotto", "pantofola",
]

# Extra RSS feeds — leak/culture focused, not brand official feeds
EXTRA_RSS_FEEDS = [
    ("https://www.soccerbible.com/feed/",  "SoccerBible"),
    ("https://www.footy-boots.com/feed/",  "Footy-Boots"),
    ("https://www.kickster.eu/feed/",      "Kickster"),
]

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

    footyheadlines.com uses .post-feed__item containers.  Each item has:
      <a class="post-feed__item-link" href="/YYYY/MM/slug.html">
        <h2 class="post-feed__item-headline">Title Here</h2>
      </a>
    No date element in the HTML — date is parsed from the URL path.
    Because we only have YYYY/MM precision we treat every story as published
    on the 1st of that month at midnight UTC for age-filtering purposes.
    Stories whose URL has no parseable date are assumed to be recent (today).
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

    # Primary: .post-feed__item  (current site structure as of 2025)
    candidates = soup.select(".post-feed__item")

    # Fallback to legacy selectors in case the site is ever restructured
    if not candidates:
        candidates = soup.select("article") or soup.select(".post")

    log.info("Candidate blocks found: %d", len(candidates))

    for position, block in enumerate(candidates):
        # ── Link & Title ─────────────────────────────────────────────────────
        link_tag = block.select_one("a.post-feed__item-link") or block.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            href = FOOTY_HEADLINES_URL.rstrip("/") + "/" + href.lstrip("/")

        # ── Only include actual footyheadlines.com articles ───────────────────
        # Partner/sponsored links redirect to external domains — skip them.
        if "footyheadlines.com" not in href:
            log.debug("Skipping off-domain link: %s", href)
            continue

        # Prefer the dedicated headline element; fall back to any hX or link text
        headline_tag = block.select_one("h2.post-feed__item-headline")
        if headline_tag:
            title = headline_tag.get_text(separator=" ", strip=True)
        else:
            title = ""
            for hx in block.find_all(["h2", "h3", "h4"]):
                t = hx.get_text(separator=" ", strip=True)
                if len(t) >= 10:
                    title = t
                    break
            if not title:
                title = link_tag.get_text(separator=" ", strip=True)

        if not title or len(title) < 10:
            continue

        # ── Quality gate: skip evergreen/archive titles ───────────────────────
        # These are listicles, guides, and archive pages — not breaking news.
        _junk_patterns = [
            r"\barchive\b", r"\bhistory\b", r"\bbest boots of\b",
            r"\bguide to\b", r"\bhow to\b", r"\ball time\b",
            r"\btop \d+\b", r"\bevery boot\b", r"\bcomplete list\b",
        ]
        title_l = title.lower()
        if any(re.search(p, title_l) for p in _junk_patterns):
            log.debug("Skipping evergreen/archive title: %r", title)
            continue

        # ── Date ─────────────────────────────────────────────────────────────
        # footyheadlines URLs give YYYY/MM only — no day.
        # Instead of using the 1st of the month (which would make a May story
        # look 10 days old on May 11th), we use page *position* as a freshness
        # proxy: the homepage is sorted newest-first, so position 0 is today.
        # We give each position ~0.4 days of age (so first 3 slots = age 0,
        # slots 4-7 = age 1, etc.) and cap at MAX_AGE_DAYS.
        story_date: datetime | None = None

        # Try an explicit <time datetime="…"> element first (most accurate)
        time_tag = block.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                raw = time_tag["datetime"][:19]
                story_date = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            except Exception:
                pass

        if story_date is not None:
            age_days = (now - story_date).days
        else:
            # No exact date — use position: top of page = freshest
            # positions 0-2 → age 0, 3-5 → age 1, 6-8 → age 2, etc.
            age_days = position // 3

        if age_days > max_age_days:
            continue  # too old

        sid = _story_id(title)
        stories.append({
            "id": sid,
            "title": title,
            "url": href,
            "date": (story_date or now).isoformat(),
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


# ---------------------------------------------------------------------------
# 1b. Nitter (Twitter/X via open frontend RSS)
# ---------------------------------------------------------------------------

def _get_working_nitter() -> "str | None":
    """Return the first Nitter instance that returns a 200."""
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(
                f"{instance}/footyheadlines/rss",
                headers=HEADERS,
                timeout=8,
            )
            if r.status_code == 200 and "<rss" in r.text[:500]:
                log.info("Nitter instance available: %s", instance)
                return instance
        except Exception:
            continue
    log.warning("No Nitter instances responded — skipping Twitter scrape.")
    return None


def scrape_nitter(max_age_days: int = MAX_AGE_DAYS) -> list[dict]:
    """
    Scrape football boot/kit tweets via Nitter RSS feeds.
    Returns same dict format as scrape_stories(), plus 'tweet_image' key.
    """
    try:
        import feedparser  # noqa: PLC0415
    except ImportError:
        log.warning("feedparser not installed — skipping Nitter.")
        return []

    nitter = _get_working_nitter()
    if not nitter:
        return []

    now = datetime.now(tz=timezone.utc)
    stories: list[dict] = []

    for account in TWITTER_ACCOUNTS:
        rss_url = f"{nitter}/{account}/rss"
        try:
            feed = feedparser.parse(rss_url)
            if not feed.entries:
                continue
            for entry in feed.entries[:25]:
                title   = entry.get("title",   "")
                summary = entry.get("summary", "")
                full    = f"{title} {BeautifulSoup(summary, 'html.parser').get_text(' ', strip=True)}"
                full_l  = full.lower()

                # Must mention boots/kits to be relevant
                if not any(kw in full_l for kw in BOOT_TWEET_KEYWORDS):
                    continue

                # Quality gate: needs at least one *action* word (not just a brand name)
                # so "Just posted an adidas ad" doesn't sneak through
                _action_words = [
                    "spotted", "leaked", "leak", "exclusive", "first look",
                    "unreleased", "prototype", "sample", "rumoured", "rumored",
                    "training", "warm-up", "warmup", "match worn", "worn by",
                    "wearing", "revealed", "reveal", "drop", "release",
                    "confirmed", "breaking", "colourway", "colorway",
                    "coming soon", "player edition", "new boot", "new kit",
                    "new jersey", "new shirt", "new cleat",
                ]
                if not any(aw in full_l for aw in _action_words):
                    log.debug("Tweet lacks action word — skipping: %r", clean[:60])
                    continue

                # ── Date ──────────────────────────────────────────────────
                published = entry.get("published_parsed")
                if published:
                    story_date = datetime(*published[:6], tzinfo=timezone.utc)
                else:
                    story_date = now
                age_days = (now - story_date).days
                if age_days > max_age_days:
                    continue

                # ── Image (from tweet media) ───────────────────────────────
                tweet_image: "str | None" = None
                img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
                if img_m:
                    img_url = img_m.group(1)
                    # Nitter proxies images — turn relative URLs absolute
                    if img_url.startswith("/"):
                        img_url = nitter + img_url
                    tweet_image = img_url

                # ── Clean headline ─────────────────────────────────────────
                clean = re.sub(r"https?://\S+", "", full).strip()
                clean = re.sub(r"\s+", " ", clean)
                # Trim to a sensible length
                if len(clean) > 120:
                    clean = clean[:117] + "…"
                if len(clean) < 15:
                    continue

                link = entry.get("link", f"https://x.com/{account}")
                if not link.startswith("http"):
                    link = f"https://x.com/{account}"

                sid = _story_id(clean)
                stories.append({
                    "id":          sid,
                    "title":       clean,
                    "url":         link,
                    "date":        story_date.isoformat(),
                    "age_days":    age_days,
                    "source":      f"@{account} on X",
                    "tweet_image": tweet_image,
                })
        except Exception as exc:
            log.warning("Nitter scrape failed for @%s: %s", account, exc)

    # De-duplicate
    seen: set[str] = set()
    unique: list[dict] = []
    for s in stories:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    unique.sort(key=lambda x: x["age_days"])
    log.info("Nitter: %d boot/kit tweets ≤ %d days old.", len(unique), max_age_days)
    return unique


# ---------------------------------------------------------------------------
# 1c. Extra RSS feeds (SoccerBible, Footy-Boots, Kickster)
# ---------------------------------------------------------------------------

def scrape_rss_feeds(max_age_days: int = MAX_AGE_DAYS) -> list[dict]:
    """Scrape additional football news RSS sources."""
    try:
        import feedparser  # noqa: PLC0415
    except ImportError:
        log.warning("feedparser not installed — skipping extra RSS.")
        return []

    now = datetime.now(tz=timezone.utc)
    stories: list[dict] = []

    for feed_url, source_name in EXTRA_RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "").strip()
                if not title or len(title) < 10:
                    continue

                # Quality gate: title must contain at least one action/news word
                title_l = title.lower()
                _rss_action_words = [
                    "spotted", "leaked", "leak", "exclusive", "first look",
                    "unreleased", "prototype", "sample", "rumoured", "rumored",
                    "training", "warm-up", "match worn", "worn by", "revealed",
                    "reveal", "drop", "release", "confirmed", "breaking",
                    "colourway", "colorway", "new boot", "new kit", "new shirt",
                    "new jersey", "new cleat", "launch", "announced", "dropped",
                    "player edition", "limited edition", "coming soon",
                ]
                if not any(aw in title_l for aw in _rss_action_words):
                    log.debug("RSS title lacks news action — skipping: %r", title[:60])
                    continue

                published = entry.get("published_parsed")
                story_date = datetime(*published[:6], tzinfo=timezone.utc) if published else now
                age_days = (now - story_date).days
                if age_days > max_age_days:
                    continue

                link = entry.get("link", "")

                # Try to pull image from feed entry
                feed_image: "str | None" = None
                media = entry.get("media_content", [])
                if media:
                    feed_image = media[0].get("url")
                if not feed_image:
                    for enc in entry.get("enclosures", []):
                        if enc.get("type", "").startswith("image"):
                            feed_image = enc.get("href") or enc.get("url")
                            break
                if not feed_image:
                    raw = (
                        entry.get("summary", "")
                        or (entry.get("content") or [{}])[0].get("value", "")
                    )
                    im = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw)
                    if im:
                        feed_image = im.group(1)

                sid = _story_id(title)
                stories.append({
                    "id":          sid,
                    "title":       title,
                    "url":         link,
                    "date":        story_date.isoformat(),
                    "age_days":    age_days,
                    "source":      source_name,
                    "tweet_image": feed_image,
                })
        except Exception as exc:
            log.warning("RSS scrape failed for %s: %s", source_name, exc)

    seen: set[str] = set()
    unique: list[dict] = []
    for s in stories:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    unique.sort(key=lambda x: x["age_days"])
    log.info("RSS feeds: %d stories ≤ %d days old.", len(unique), max_age_days)
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
    # LEAKED: rumours and unreleased early sightings
    ("LEAKED",   ["leaked", "leak", "unreleased", "prototype", "sample", "rumoured",
                  "rumored", "rumour", "rumor", "exclusive", "first look", "first-look",
                  "player edition", "pe boot", "unboxing"]),
    # SPOTTED: athlete seen wearing boots/kit before official reveal
    ("SPOTTED",  ["spotted", "training", "training ground", "warm-up", "warmup",
                  "warm up", "match worn", "game worn", "worn by", "wearing",
                  "on feet", "on pitch"]),
    # BREAKING: official confirmations and announcements
    ("BREAKING", ["breaking", "confirmed", "official", "announced"]),
    # DROPPED: product launches and release-day posts
    ("DROPPED",  ["release", "drop", "launch", "on sale", "available now", "buy now",
                  "dropping", "coming soon"]),
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
        "LEAKED":   "#FootballLeaks",
        "SPOTTED":  "#BootSpotted",
        "BREAKING": "#BreakingNews",
        "DROPPED":  "#JustDropped",
        "NEWS":     "#FootballBoots",
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


def find_image(title: str, preferred_url: "str | None" = None) -> "bytes | None":
    """
    Image search with priority order:
      1. preferred_url  — direct image from the tweet / RSS feed (most relevant)
      2. Google Custom Search
      3. Pexels
      4. Generic fallback query

    preferred_url is passed for stories that carry a tweet_image / feed_image.
    """
    # ── Priority: use the image that came with the story ─────────────────────
    if preferred_url:
        log.info("Trying preferred (tweet/RSS) image: %s", preferred_url)
        img = _download_image(preferred_url)
        if img and len(img) > 5000:
            log.info("Using preferred image (%d bytes).", len(img))
            return img
        log.debug("Preferred image unavailable — falling back to search.")

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

    Strategy:
      - If instagram_session.json exists (generated locally via generate_session.py),
        load those cookies WITHOUT re-logging in from the GitHub Actions IP.
        GitHub/Azure IPs are blacklisted by Instagram for fresh logins, but
        existing authenticated sessions/cookies work fine from any IP.
      - If no session file, attempt a fresh login (will only work from a
        residential IP, i.e. when run locally).

    To set up: run `python posts/generate_session.py` once on your local
    machine, then commit posts/instagram_session.json to the repo.
    """
    if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        log.error("INSTAGRAM_USERNAME or INSTAGRAM_PASSWORD not set in environment.")
        return False

    try:
        from instagrapi import Client  # noqa: PLC0415
        from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes  # noqa: PLC0415
    except ImportError:
        log.error("instagrapi is not installed. Add it to requirements.")
        return False

    def _fresh_client() -> "Client":
        c = Client()
        c.set_locale("en_US")
        c.set_timezone_offset(0)
        return c

    cl = _fresh_client()
    session_loaded = False

    if INSTAGRAM_SESSION_FILE.exists():
        # ── Session-only path (GitHub Actions) ───────────────────────────────
        # Load persisted cookies; do NOT call cl.login() — that triggers a new
        # authentication request which Instagram rejects from data-centre IPs.
        log.info("Loading Instagram session from %s", INSTAGRAM_SESSION_FILE)
        try:
            cl.load_settings(str(INSTAGRAM_SESSION_FILE))
            # Reuse the stored cookies by setting account ID via username
            cl.get_timeline_feed()   # lightweight test — raises if session dead
            session_loaded = True
            log.info("Session is valid — skipping re-login.")
        except Exception as exc:
            log.warning("Stored session is invalid (%s). Will attempt fresh login.", exc)
            cl = _fresh_client()
    else:
        log.info("No session file found — will attempt fresh login (needs residential IP).")

    if not session_loaded:
        # ── Fresh-login path (local machine only) ────────────────────────────
        log.info("Logging into Instagram as @%s …", INSTAGRAM_USERNAME)
        try:
            cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            log.info("Login successful.")
        except Exception as exc:
            log.error("Instagram login failed: %s", exc)
            log.error(
                "If running on GitHub Actions, generate a session first: "
                "run `python posts/generate_session.py` locally, then commit "
                "posts/instagram_session.json to the repo."
            )
            return False

    # Persist updated session for next run
    try:
        cl.dump_settings(str(INSTAGRAM_SESSION_FILE))
        log.info("Session saved to %s", INSTAGRAM_SESSION_FILE)
    except Exception as exc:
        log.warning("Could not save session: %s", exc)

    # ── Prepare image: Instagram requires JPEG, max portrait ratio 4:5 ────────
    import tempfile as _tmpfile
    from PIL import Image as _Image

    upload_path = image_path
    _tmp_jpeg = None
    try:
        with _Image.open(image_path) as img:
            w, h = img.size
            # Crop to 4:5 (1080×1350) if image is taller than that ratio
            max_h = int(w * 5 / 4)
            if h > max_h:
                # Centre-crop: remove equal slices from top and bottom
                top = (h - max_h) // 2
                img = img.crop((0, top, w, top + max_h))
                log.info("Cropped image from %dx%d to %dx%d (4:5 ratio)", w, h, w, max_h)

            # Convert to JPEG (Instagram's preferred format)
            _tmp_fd, _tmp_path = _tmpfile.mkstemp(suffix=".jpg",
                                                   dir=str(OUTPUT_DIR))
            import os as _os; _os.close(_tmp_fd)
            img.convert("RGB").save(_tmp_path, "JPEG", quality=95)
            upload_path = _tmp_path
            _tmp_jpeg = _tmp_path
            log.info("Converted to JPEG for upload: %s", upload_path)
    except Exception as exc:
        log.warning("Image prep failed (%s) — uploading original PNG", exc)

    # ── Monkey-patch instagrapi for Instagram's updated configure response ────
    # As of 2025, /api/v1/media/configure/ returns {"status":"ok"} with no
    # media payload.  Patch _extract_configured_media_or_raise to detect this
    # and fetch the freshly-uploaded media via user_medias instead.
    from instagrapi.mixins import media as _media_mixin  # noqa: PLC0415

    _original_extract = _media_mixin.MediaMixin._extract_configured_media_or_raise

    def _patched_extract(self, configured, exception_cls, context):
        last = self.last_json if isinstance(self.last_json, dict) else {}
        cfg  = configured    if isinstance(configured,    dict) else {}
        # Success path: status ok but no media key → fetch the latest post
        if last.get("status") == "ok" or cfg.get("status") == "ok":
            import time as _t; _t.sleep(2)
            try:
                medias = self.user_medias_v1(self.user_id, amount=1)
                if medias:
                    log.info("Fetched latest media after configure: %s", medias[0].pk)
                    return medias[0]
            except Exception as _fe:
                log.warning("Could not fetch latest media: %s", _fe)
            # Return a minimal stub so the pipeline can mark the story posted
            from instagrapi.types import Media as _Media  # noqa: PLC0415
            return _Media(pk="0", id="0", code="", media_type=1,
                         taken_at=__import__("datetime").datetime.now())
        return _original_extract(self, configured, exception_cls, context)

    _media_mixin.MediaMixin._extract_configured_media_or_raise = _patched_extract

    # Upload the post
    log.info("Uploading photo to Instagram …")
    try:
        import time as _time
        _time.sleep(1)
        media = cl.photo_upload(
            path=upload_path,
            caption=caption,
            extra_data={"custom_accessibility_caption": "", "like_and_view_counts_disabled": 0},
        )
        if media.code:
            log.info("Posted! Media ID: %s  URL: https://www.instagram.com/p/%s/",
                     media.pk, media.code)
        else:
            log.info("Posted! (media details unavailable — check @footyculturehq)")
        if _tmp_jpeg:
            import os as _os2; _os2.unlink(_tmp_jpeg)
        return True
    except Exception as exc:
        log.error("Instagram photo upload failed: %s", exc, exc_info=True)
        if _tmp_jpeg:
            try:
                import os as _os3; _os3.unlink(_tmp_jpeg)
            except Exception:
                pass
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("=== Footy Culture HQ pipeline starting ===")

    # ── Load history ─────────────────────────────────────────────────────────
    posted = _load_posted()
    log.info("Stories already posted: %d", len(posted))

    # ── Scrape all sources ────────────────────────────────────────────────────
    fh_stories   = scrape_stories()
    nitter_stories = scrape_nitter()
    rss_stories  = scrape_rss_feeds()

    all_stories = fh_stories + nitter_stories + rss_stories
    log.info(
        "Total candidates — FootyHeadlines: %d  Nitter: %d  RSS: %d  Combined: %d",
        len(fh_stories), len(nitter_stories), len(rss_stories), len(all_stories),
    )

    if not all_stories:
        log.warning("No stories found from any source. Exiting without posting.")
        return

    # ── Merge: sort freshest-first, deduplicate ───────────────────────────────
    all_stories.sort(key=lambda x: x["age_days"])
    seen_ids: set[str] = set()
    unique: list[dict] = []
    for s in all_stories:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            unique.append(s)
    log.info("Unique stories after dedup: %d", len(unique))

    # ── Pick first unposted story ─────────────────────────────────────────────
    posted_ids = {p.get("id") for p in posted}
    story: "dict | None" = None
    for s in unique:
        if s["id"] not in posted_ids:
            story = s
            break

    if story is None:
        log.info("All recent stories have already been posted. Nothing to do.")
        return

    log.info(
        "Selected story: %r  source=%s  age=%d days",
        story["title"],
        story.get("source", "FootyHeadlines"),
        story["age_days"],
    )

    # ── Prepare content ──────────────────────────────────────────────────────
    tag = pick_tag(story["title"])
    headline = format_headline(story["title"])
    caption = build_caption(story["title"], tag)

    log.info("Tag: %s | Headline: %r", tag, headline)
    log.info("Caption: %s", caption)

    # ── Find image ────────────────────────────────────────────────────────────
    # Pass tweet_image / feed_image as the preferred URL so we use the actual
    # boot/kit photo attached to the tweet or RSS entry before falling back to
    # Google / Pexels searches.
    preferred_img_url: "str | None" = story.get("tweet_image")
    img_bytes = find_image(story["title"], preferred_url=preferred_img_url)
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
