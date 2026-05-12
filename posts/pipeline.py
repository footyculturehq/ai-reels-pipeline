"""
Footy Culture HQ — Automated Instagram Posting Pipeline
--------------------------------------------------------
Runs 2x/day via GitHub Actions (noon and 7pm UTC).

Flow:
  1. Scrape footyheadlines.com, Nitter, and RSS feeds for boot/kit news ≤ 3 days old
  2. Skip stories already in posted_stories.json; enforce max 2 posts/24h
  3. Score stories 0-10 — only post if score ≥ 7 (big clubs, big players, hot models)
  4. Inject hype word into headline (LEAKED:, INSANE., CLEAN., etc.)
  5. Find ONE best image: article renders → tweet/RSS image → Pexels
  6. Generate a single 1080×1350 magazine-cover card using create_post.py
  7. Post to Instagram via instagrapi; append to posted_stories.json

CLI flags:
  --dry-run   Generate card locally but skip Instagram upload

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
# 2. Category detection + scoring + headline tools
# ---------------------------------------------------------------------------

def pick_category(title: str) -> str:
    """
    Map story title to a display category for the card badge.
    Returns one of: KIT DROP / BOOT LAUNCH / SIGNING / COLLAB / VAULT /
                    LEAKED / SPOTTED / FOOTBALL
    """
    t = title.lower()
    if any(w in t for w in ["collab", "collaboration", " x ", "x nike", "x adidas"]):
        return "COLLAB"
    if any(w in t for w in ["retro", "vault", "reissue", "og ", "classic", "archive"]):
        return "VAULT"
    if any(w in t for w in ["signing", "joins", "signed", "transfer", "deal", "contract"]):
        return "SIGNING"
    if any(w in t for w in ["boot launch", "boot drop", "new boot", "new cleat",
                             "released", "available", "on sale", "buy now"]):
        return "BOOT LAUNCH"
    if any(w in t for w in ["boot", "boots", "cleat", "cleats"]):
        if any(w in t for w in ["leaked", "leak", "spotted", "training", "worn"]):
            return "LEAKED"
        return "BOOT LAUNCH"
    if any(w in t for w in ["kit reveal", "kit launch", "kit drop", "new kit",
                             "home kit", "away kit", "third kit"]):
        return "KIT DROP"
    if any(w in t for w in ["kit", "jersey", "shirt", "strip"]):
        if any(w in t for w in ["leaked", "leak"]):
            return "LEAKED"
        return "KIT DROP"
    if any(w in t for w in ["spotted", "training", "warm-up", "warmup", "match worn",
                             "worn by", "wearing", "on feet"]):
        return "SPOTTED"
    if any(w in t for w in ["leaked", "leak", "unreleased", "prototype", "rumoured"]):
        return "LEAKED"
    return "FOOTBALL"


# Legacy alias used in scoring logic
def pick_tag(title: str) -> str:
    return pick_category(title)


def score_story(story: dict) -> tuple[int, str]:
    """
    Score a story 0–10 for post-worthiness using tiered entity weights,
    content-quality multipliers, hard filters, and cross-source confirmation.

    Hard filters return score=0 immediately (skip regardless of entity).
    Baseline = 2; must score ≥7 to post.

    Returns (score, reason_string).
    """
    t     = story["title"].lower()
    score = 2       # baseline — well below threshold
    reasons: list[str] = []

    # ══════════════════════════════════════════════════════════════════════════
    # HARD FILTERS — skip entirely, no matter how big the entity
    # ══════════════════════════════════════════════════════════════════════════

    # 1. Pure date tease — product not visible yet ("Coming May 15", "Dropping June")
    if re.search(
        r"(coming|dropping|launching|releasing|arrives?|available)\s+"
        r"(jan|feb|mar|apr|may|june?|july?|aug|sep|oct|nov|dec|\d{1,2})",
        t,
    ):
        return 0, "HARD FILTER: date tease — product not visible"

    # 2. Concept / fan-made kits — not real product, never accurate image
    if any(w in t for w in ["concept", "fan-made", "fan made", "fan kit",
                             "concept kit", "reimagined"]):
        return 0, "HARD FILTER: concept/fan-made"

    # 3. Poll / vote / opinion articles — no product news
    if any(w in t for w in ["voted", "vote:", "poll:", "worst kit", "best kit of",
                             "ranked:", "ranking"]):
        return 0, "HARD FILTER: poll/vote article"

    # 4. Pure roundup / overview — usually collage, no single product
    if re.search(r"\b(roundup|round-up|overview|all \d+ kits|every kit)\b", t):
        return 0, "HARD FILTER: roundup/collage"

    # 5. Teaser with nothing revealed — "teased" but no leaked/spotted qualifier
    if "teased" in t and not any(w in t for w in ["leaked", "spotted", "revealed", "confirmed"]):
        return 0, "HARD FILTER: tease with no product reveal"

    # ══════════════════════════════════════════════════════════════════════════
    # ENTITY SCORING — tiered by audience size
    # ══════════════════════════════════════════════════════════════════════════

    # ── Clubs: Tier 1 (+5) — mass global fanbase ──────────────────────────────
    tier1_clubs = [
        "real madrid", "barcelona", "manchester united", "man utd",
        "arsenal", "liverpool", "psg", "paris saint-germain",
    ]
    # ── Clubs: Tier 2 (+3) — big, passionate fanbases ────────────────────────
    tier2_clubs = [
        "manchester city", "man city", "chelsea", "tottenham", "spurs",
        "bayern", "juventus", "ac milan", "inter milan",
    ]
    # ── Clubs: Tier 3 (+1) — popular but smaller reach ───────────────────────
    tier3_clubs = [
        "dortmund", "atletico", "atletico madrid", "napoli",
        "roma", "lazio", "sevilla", "porto", "benfica",
    ]

    if any(c in t for c in tier1_clubs):
        score += 5; reasons.append("tier-1 club +5")
    elif any(c in t for c in tier2_clubs):
        score += 3; reasons.append("tier-2 club +3")
    elif any(c in t for c in tier3_clubs):
        score += 1; reasons.append("tier-3 club +1")

    # ── National teams (+3 always; massive audiences) ─────────────────────────
    nat_teams = [
        "brazil", "argentina", "france", "england", "germany",
        "portugal", "spain", "italy", "mexico", "netherlands",
        "usa", "japan", "south korea",
    ]
    if any(n in t for n in nat_teams):
        score += 3; reasons.append("national team +3")

    # ── Players: Star tier (+5) — guaranteed massive engagement ──────────────
    star_players = [
        "mbappe", "messi", "ronaldo", "haaland", "yamal", "bellingham",
    ]
    # ── Players: Top tier (+3) — big accounts, strong engagement ─────────────
    top_players = [
        "vinicius", "salah", "saka", "kane", "de bruyne", "pedri",
        "rashford", "neymar", "lewandowski", "son", "martinelli",
        "pulisic", "foden", "odegaard", "grealish", "mount",
        "osimhen", "dybala", "benzema", "modric", "kroos",
    ]

    if any(p in t for p in star_players):
        score += 5; reasons.append("star player +5")
    elif any(p in t for p in top_players):
        score += 3; reasons.append("top player +3")

    # ── Brands: Top tier (+2) ─────────────────────────────────────────────────
    if any(b in t for b in ["nike", "adidas"]):
        score += 2; reasons.append("top brand +2")
    elif any(b in t for b in ["puma", "new balance"]):
        score += 1; reasons.append("mid brand +1")

    # ── Boot models: Popular silo (+2) ────────────────────────────────────────
    hot_models = [
        "mercurial", "predator", "phantom", "tiempo", "superfly",
        "copa", "future", "ultra", "king", "tekela", "furon",
        "f50", "x speedflow", "speedportal", "thrasher",
    ]
    if any(m in t for m in hot_models):
        score += 2; reasons.append("hot boot model +2")

    # ══════════════════════════════════════════════════════════════════════════
    # CONTENT QUALITY — bonus multipliers
    # ══════════════════════════════════════════════════════════════════════════

    if any(w in t for w in ["collab", "collaboration", " x nike", " x adidas", " x puma"]):
        score += 4; reasons.append("player×brand collab +4")
    if any(w in t for w in ["retro", "vault", "reissue", "og ", "classic", "archive",
                             "remake", "throwback"]):
        score += 3; reasons.append("retro/vault reissue +3")
    if any(w in t for w in ["leaked", "leak"]):
        score += 2; reasons.append("leaked before official +2")
    if any(w in t for w in ["spotted", "training", "on feet", "worn by", "match worn"]):
        score += 1; reasons.append("spotted on feet +1")
    if any(w in t for w in ["confirmed", "official", "released", "launch", "on sale"]):
        score += 1; reasons.append("official confirm +1")

    # ── Cross-source confirmation (+2) ────────────────────────────────────────
    # Set by main() when 2+ whitelisted sources cover the same story within 24h
    if story.get("cross_source_confirmed"):
        score += 2; reasons.append("multi-source confirmed +2")

    # ══════════════════════════════════════════════════════════════════════════
    # PENALTIES — known low-performers
    # ══════════════════════════════════════════════════════════════════════════

    # Niche training/anthem apparel — nobody cares
    niche_items = [
        "anthem jacket", "anthem track", "anthem top", "anthem vest",
        "woven jacket", "rain jacket", "tracksuit",
        "training shirt", "training top", "training jacket", "pre-match",
    ]
    if any(n in t for n in niche_items):
        score -= 4; reasons.append("niche apparel −4")

    # Obscure clubs — small audience
    obscure_clubs = [
        "palermo", "galatasaray", "lyon", "burnley", "nottingham",
        "brentford", "fulham", "wolves", "brighton", "luton",
        "lecce", "sassuolo", "elche", "valladolid", "girona",
        "odense", "copenhagen", "hellas", "salernitana",
    ]
    if any(c in t for c in obscure_clubs):
        score -= 2; reasons.append("obscure club −2")

    # Stale news (>2 days old)
    age = story.get("age_days", 0)
    if age > 2:
        score -= 2; reasons.append(f"stale news ({age}d old) −2")

    # Editorial non-news
    if any(w in t for w in ["away kit info", "info:", "details:", "what we know",
                             "everything we know"]):
        score -= 2; reasons.append("editorial info piece −2")

    score = max(0, min(10, score))
    return score, " | ".join(reasons) if reasons else "baseline"


# ---------------------------------------------------------------------------
# 3. Format headline + hype-word injector
# ---------------------------------------------------------------------------

def format_headline(title: str) -> str:
    """
    Clean up the raw article title for the card headline.

    Rules (in order):
      1. Strip source attribution (— Footy Headlines etc.)
      2. Strip year-range tokens (26-27, 2026-27) — look clumsy at 120px
      3. Strip EDITORIAL SUBTITLES — the part after " - " when the suffix is
         a comparison, description, or non-news clause (e.g. "Short-Sleeve vs
         Long-Sleeve", "Launch Pictures", "What We Know").
         Only drop the suffix if it contains none of the news-value keywords
         (leaked / spotted / official / collab / confirmed).
      4. Hard-cap at 72 chars with ellipsis.
    """
    # 1. Source attribution
    title = re.sub(r"\s*[|—–-]\s*(footy headlines?|footyheadlines\.com).*$",
                   "", title, flags=re.IGNORECASE).strip()

    # 2. Year ranges
    title = re.sub(r'\b20\d{2}[-–]\d{2,4}\b', '', title)
    title = re.sub(r'\b\d{2}-\d{2}\b', '', title)
    title = re.sub(r'\s+', ' ', title).strip()

    # 3. Editorial subtitles — strip everything after the first " - " separator
    #    UNLESS the subtitle itself carries news value.
    _keep_subtitle_words = {
        "leaked", "spotted", "official", "confirmed", "breaking",
        "exclusive", "collab", "collaboration", "signing", "transfer",
        "released", "launch", "drop",
    }
    parts = re.split(r'\s*[-–—]\s*', title, maxsplit=1)
    if len(parts) == 2:
        main_clause, subtitle = parts[0].strip(), parts[1].strip()
        subtitle_lower = subtitle.lower()
        if not any(w in subtitle_lower for w in _keep_subtitle_words):
            # Subtitle is descriptive/editorial — drop it
            title = main_clause

    title = re.sub(r'\s+', ' ', title).strip()

    # 4. Length cap
    if len(title) > 72:
        title = title[:70].rsplit(" ", 1)[0] + "…"
    return title.strip()


_HYPE_WORDS = {
    "LEAKED":       ["LEAKED:", "FIRST LOOK:", "EXCLUSIVE:"],
    "SPOTTED":      ["SPOTTED:", "CAUGHT:", "SEEN:"],
    "KIT DROP":     ["CLEAN.", "INSANE.", "NEW:"],
    "BOOT LAUNCH":  ["STRIKING.", "NEW:", "INSANE."],
    "SIGNING":      ["BREAKING:", "OFFICIAL:", "CONFIRMED:"],
    "COLLAB":       ["INSANE.", "MASSIVE:", "CLEAN."],
    "VAULT":        ["CLEAN.", "CLASSIC.", "VAULT:"],
    "FOOTBALL":     ["NEW:", "BREAKING:", "LATEST:"],
}


def inject_hype(headline: str, category: str) -> str:
    """
    Prepend a contextually appropriate hype word to the headline.
    Picks deterministically based on title hash so reruns are stable.
    """
    import hashlib
    options = _HYPE_WORDS.get(category, _HYPE_WORDS["FOOTBALL"])
    idx = int(hashlib.md5(headline.encode()).hexdigest(), 16) % len(options)
    return f"{options[idx]} {headline}"


# ---------------------------------------------------------------------------
# 4. Build Instagram caption (spec format)
# ---------------------------------------------------------------------------

def build_caption(title: str, category: str) -> str:
    """
    Format per spec:
      Line 1: Headline
      Line 2: blank
      Line 3: 1–2 sentence context
      Line 4: blank
      Line 5: CTA
      Line 6: blank
      Line 7: Hashtags (max 8)
    """
    import hashlib

    t = title.lower()

    # ── Line 1: headline ─────────────────────────────────────────────────────
    headline_line = title

    # ── Line 3: 1-2 sentence context ─────────────────────────────────────────
    context_map = {
        "LEAKED":       "Leaked before the brand is ready to announce — hit the link in bio for the full story.",
        "SPOTTED":      "Caught on feet before the official reveal. The leaks always come here first.",
        "KIT DROP":     "The new kit is official. Full details and release info at the link in bio.",
        "BOOT LAUNCH":  "New colourway just hit. Check the link in bio for pricing and release date.",
        "SIGNING":      "The deal is done. More details at the link in bio.",
        "COLLAB":       "The collab is real and it looks insane. Full details in bio.",
        "VAULT":        "The classic is back. Retro lovers, this one's for you.",
        "FOOTBALL":     "Full story at the link in bio. Follow for daily kit and boot news.",
    }
    context = context_map.get(category, context_map["FOOTBALL"])

    # ── Line 5: CTA ───────────────────────────────────────────────────────────
    cta = "🔔 Drop alerts → link in bio"

    # ── Line 7: Hashtags (max 8, relevant only) ───────────────────────────────
    hashtags: list[str] = ["#footballculture", "#footballboots"]

    brand_tags = {
        "nike":        "#nike #nikefootball",
        "adidas":      "#adidas #adidasfootball",
        "puma":        "#puma #pumafootball",
        "new balance": "#newbalance",
        "umbro":       "#umbro",
        "under armour":"#underarmour",
        "castore":     "#castore",
    }
    for brand, ht in brand_tags.items():
        if brand in t:
            hashtags.extend(ht.split())
            break

    if any(w in t for w in ["kit", "jersey", "shirt"]):
        hashtags.append("#kitdrops")
        hashtags.append("#soccerkits")
    elif any(w in t for w in ["boot", "cleat"]):
        hashtags.append("#footballboots")

    club_tags = {
        "arsenal": "#arsenal", "liverpool": "#liverpool",
        "chelsea": "#chelsea", "manchester united": "#manutd",
        "manchester city": "#mancity", "real madrid": "#realmadrid",
        "barcelona": "#fcbarcelona", "psg": "#psg",
        "juventus": "#juventus", "bayern": "#fcbayern",
    }
    for club, ht in club_tags.items():
        if club in t:
            hashtags.append(ht)
            break

    hashtags.append("#footyculturehq")

    # Deduplicate, cap at 8
    seen_ht: set[str] = set()
    clean_tags: list[str] = []
    for h in hashtags:
        if h not in seen_ht:
            seen_ht.add(h)
            clean_tags.append(h)
    tag_block = " ".join(clean_tags[:8])

    return (
        f"{headline_line}\n\n"
        f"{context}\n\n"
        f"{cta}\n\n"
        f"{tag_block}"
    )


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

def _upgrade_blogger_url(url: str) -> str:
    """
    FootyHeadlines is hosted on Blogger / Google CDN.
    URLs contain a size token like /s400/, /s640/, /s1600/.
    Replace with /s1200/ to get a high-resolution version
    (s1600 is sometimes blocked; s1200 is reliably served).
    """
    return re.sub(r'/s\d{2,4}(-[^/]*)/', '/s1200/', url)


def _img_hash(data: bytes) -> str:
    """MD5 of a thumbnail — fast perceptual near-duplicate detector."""
    import hashlib
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB").resize((32, 32))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=50)
        return hashlib.md5(buf.getvalue()).hexdigest()
    except Exception:
        import hashlib
        return hashlib.md5(data[:4096]).hexdigest()


def _process_image_bytes(data: bytes, img_url: str) -> "bytes | None":
    """
    Validate dimensions, crop landscape/split-panels to left half.
    Returns processed bytes or None if the image should be skipped.
    """
    try:
        img_check = Image.open(io.BytesIO(data))
        w, h = img_check.size

        # Skip thumbnails / icons (related-post widgets, ads, etc.)
        if w < 500 or h < 400:
            log.debug("Skipping small image (%dx%d): %s", w, h, img_url[:70])
            return None

        # Landscape / split-panel → crop to left half (one clean product view)
        ar = w / h
        if ar > 1.35:
            crop_w = w // 2
            cropped = img_check.crop((0, 0, crop_w, h))
            buf = io.BytesIO()
            cropped.convert("RGB").save(buf, "JPEG", quality=92)
            data = buf.getvalue()
            log.debug("Cropped wide image (ar=%.2f) to left half: %s", ar, img_url[:70])
    except Exception:
        pass  # accept as-is if we can't check

    return data


def scrape_article_images(url: str, max_images: int = 4,
                          is_kit: bool = False) -> "list[bytes]":
    """
    Fetch the actual article page and pull out product images.
    Returns up to max_images image-byte chunks — the REAL renders/photos
    for the story, not generic stock.

    WATERMARK STRATEGY
    ──────────────────
    footyheadlines creates their own exclusive KIT renders and stamps
    "FOOTYHEADLINES" across them — those are ALWAYS watermarked.
    For KIT stories we therefore take ONLY the og:image (the Twitter Card /
    article header, often an official brand render) and skip the in-article
    <a href> images entirely.

    For BOOT stories the in-article images are official Adidas/Nike press
    photos — no watermark. We fetch those freely.

    Duplicate detection uses an MD5 of a 32×32 thumbnail so near-identical
    images from different CDN size tokens are caught.
    """
    if "footyheadlines.com" not in url:
        return []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        log.debug("Article fetch failed for %s: %s", url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    found_urls: list[str] = []

    def _add(u: str) -> None:
        if not u or not u.startswith("http"):
            return
        if any(skip in u.lower() for skip in
               ["logo", "icon", "avatar", "banner", "ad-", "/ads/",
                "spinner", "loading", "placeholder"]):
            return
        u = _upgrade_blogger_url(u)
        if u not in found_urls:
            found_urls.append(u)

    # ── 1. og:image (hero shot — always collected) ────────────────────────────
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        _add(og["content"])

    if not is_kit:
        # ── Boot/general: grab <a href> in-article images ──────────────────────
        # footyheadlines lazy-loads: <img src="data:image/svg+xml,..."> wrapped
        # in <a href="https://blogger.googleusercontent.com/...actual.jpg">.
        #
        # CRITICAL cap: product images appear FIRST in the HTML; related-post
        # thumbnails immediately follow.  Cap at 1 <a> link to stay in the main
        # content zone — og:image (hero) + 1 product close-up = 2 clean slides.
        # (Strategy B / <img> tag scan was removed; it picked up related posts.)
        a_link_cap   = 1
        a_link_count = 0
        for a_tag in soup.find_all("a", href=True):
            if a_link_count >= a_link_cap:
                break
            if not a_tag.find("img"):
                continue
            href = a_tag["href"]
            if any(token in href.lower() for token in
                   ["googleusercontent.com", "blogger.com/img", "bp.blogspot"]):
                before = len(found_urls)
                _add(href)
                if len(found_urls) > before:
                    a_link_count += 1
    else:
        log.info("Kit story — skipping in-article renders (watermarked). "
                 "Using og:image only; extra slides from Google.")

    log.info("Article %s — found %d candidate image URLs (is_kit=%s)",
             url, len(found_urls), is_kit)

    collected: list[bytes] = []
    seen_hashes: set[str] = set()

    for img_url in found_urls[:max_images * 3]:
        if len(collected) >= max_images:
            break
        data = _download_image(img_url)
        if not data or len(data) < 10_000:
            continue

        data = _process_image_bytes(data, img_url)
        if data is None:
            continue

        # Perceptual duplicate check (catches same image at different CDN sizes)
        h = _img_hash(data)
        if h in seen_hashes:
            log.debug("Skipping near-duplicate image: %s", img_url[:70])
            continue
        seen_hashes.add(h)

        collected.append(data)
        log.info("  Article image %d: %s", len(collected), img_url[:80])

    log.info("Scraped %d usable images from article.", len(collected))
    return collected


def _story_content_type(title: str) -> str:
    """Return 'boot', 'kit', or 'general' based on title keywords."""
    t = title.lower()
    if any(w in t for w in ["boot", "boots", "cleat", "cleats"]):
        return "boot"
    if any(w in t for w in ["kit", "jersey", "shirt", "strip", "jacket", "tracksuit"]):
        return "kit"
    return "general"


def _build_search_query(title: str) -> str:
    """
    Build an accurate Pexels/Google search query from the story title.
    - Strips year ranges (26-27, 2026-27) that search engines won't find
    - Uses 'football kit' for kit stories, 'football boots' for boot stories
    - Extracts the most meaningful terms (brand + specific item)
    """
    # Remove year ranges like "26-27", "2025-26", "2026"
    clean = re.sub(r'\b20\d{2}[-–]\d{2,4}\b', '', title)
    clean = re.sub(r'\b\d{2}-\d{2}\b', '', clean)
    # Remove boilerplate suffixes
    clean = re.sub(r'\s*[|—–-]\s*(footy headlines?|footyheadlines\.com).*$', '', clean, flags=re.IGNORECASE)
    # Remove common filler words
    clean = re.sub(r'\b(home|away|third|fourth|alternate|pre-match|training|launch|pictures?|info|design)\b',
                   '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'\s+', ' ', clean).strip()

    content_type = _story_content_type(title)
    if content_type == "boot":
        suffix = "football boots"
    elif content_type == "kit":
        suffix = "football kit"
    else:
        suffix = "football"

    # Take first ~4 meaningful words + suffix
    words = [w for w in clean.split() if len(w) > 2][:4]
    return " ".join(words) + " " + suffix if words else suffix


def search_pexels_images(query: str, n: int = 4) -> "list[bytes]":
    """
    Search Pexels for up to n portrait photos.
    Returns list of raw image bytes (all successfully downloaded).
    """
    if not PEXELS_API_KEY:
        log.warning("PEXELS_API_KEY not set — skipping Pexels search.")
        return []

    log.info("Pexels search (want %d): %r", n, query)
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "per_page": min(n * 3, 20), "orientation": "portrait"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Pexels search failed: %s", exc)
        return []

    results: list[bytes] = []
    for photo in data.get("photos", []):
        if len(results) >= n:
            break
        img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
        if not img_url:
            continue
        img_bytes = _download_image(img_url)
        if img_bytes:
            results.append(img_bytes)
            log.info("Pexels image %d/%d: %s", len(results), n, img_url[:80])

    log.info("Pexels returned %d images for %r", len(results), query)
    return results


# Keep single-image wrappers for backward compat
def search_pexels_image(query: str) -> "bytes | None":
    results = search_pexels_images(query, n=1)
    return results[0] if results else None


def _is_specific_story(title: str) -> bool:
    """
    Return True if the story is about a specific club, player, or product —
    i.e. Pexels stock photos will almost certainly be the WRONG thing.
    We should prefer a dark-background placeholder over a mismatched image.
    """
    t = title.lower()
    specific_terms = [
        # Big clubs
        "manchester united", "man utd", "arsenal", "liverpool", "chelsea",
        "manchester city", "man city", "tottenham", "spurs", "real madrid",
        "barcelona", "psg", "paris saint-germain", "bayern", "juventus",
        "ac milan", "inter milan", "dortmund", "atletico", "napoli",
        "brazil", "england", "france", "germany", "argentina",
        "portugal", "spain", "italy", "mexico",
        # Big players
        "mbappe", "haaland", "salah", "ronaldo", "messi", "bellingham",
        "vinicius", "saka", "kane", "de bruyne", "pedri", "yamal",
        # Specific boot models
        "mercurial", "predator", "phantom", "tiempo", "superfly",
        "copa", "future", "ultra", "king", "tekela", "furon",
        "f50", "speedportal", "thrasher",
    ]
    return any(term in t for term in specific_terms)


def find_images(
    title: str,
    preferred_url: "str | None" = None,
    article_url: "str | None" = None,
    n: int = 3,
) -> "list[bytes]":
    """
    Find up to n images that accurately match the story.

    Priority order:
      1. Actual article images (scraped from footyheadlines page) — always
         accurate; landscape split-panels are cropped to left half.
      2. Tweet / RSS attached image (if story came from Nitter/RSS).
      3. Google Custom Search image.
      4. Pexels — ONLY for non-specific / generic stories.
         For stories about a specific club, player, or boot model, Pexels
         will return the wrong product. In that case we return an empty list
         so create_post falls back to a clean dark-background card.
    """
    collected: list[bytes] = []

    # ── Priority 1: scrape actual article images ──────────────────────────────
    if article_url:
        is_kit = _story_content_type(title) == "kit"
        article_imgs = scrape_article_images(article_url, max_images=n, is_kit=is_kit)
        if article_imgs:
            log.info("Using %d article images (accurate product renders).", len(article_imgs))
            # For kit stories we only got og:image from article; if we need more
            # slides fall through to Google below rather than returning early.
            if not is_kit or len(article_imgs) >= n:
                return article_imgs[:n]
            collected.extend(article_imgs)

    # ── Priority 2: tweet/RSS attached image ─────────────────────────────────
    if preferred_url:
        log.info("Trying preferred (tweet/RSS) image: %s", preferred_url)
        img = _download_image(preferred_url)
        if img and len(img) > 5000:
            # Check and crop if landscape
            try:
                im = Image.open(io.BytesIO(img))
                if im.width / im.height > 1.35:
                    crop_w = im.width // 2
                    im = im.crop((0, 0, crop_w, im.height))
                    buf = io.BytesIO()
                    im.convert("RGB").save(buf, "JPEG", quality=92)
                    img = buf.getvalue()
            except Exception:
                pass
            collected.append(img)
            log.info("Preferred image added.")

    if len(collected) >= n:
        return collected[:n]

    # ── Build fact-checked search query ──────────────────────────────────────
    query = _build_search_query(title)
    log.info("Image search query: %r  (content type: %s)",
             query, _story_content_type(title))

    # ── Priority 3: Google Custom Search ─────────────────────────────────────
    if len(collected) < n and GOOGLE_API_KEY:
        img = search_google_image(query)
        if img:
            collected.append(img)

    # ── Priority 4: Pexels — ONLY for non-specific stories ───────────────────
    # Pexels doesn't have new leaked kits or unreleased boots.
    # Using it for "Arsenal 26-27 Home Kit Leaked" would show a random jersey.
    # Better to use a dark branded card than post the wrong product.
    if len(collected) < n:
        if _is_specific_story(title):
            log.info(
                "Specific story — skipping Pexels to avoid image mismatch. "
                "Will use dark placeholder for missing slides."
            )
        else:
            still_need = n - len(collected)
            pexels_imgs = search_pexels_images(query, n=still_need + 1)
            for img in pexels_imgs:
                if len(collected) >= n:
                    break
                collected.append(img)

    log.info("Total images found: %d / %d requested", len(collected), n)
    return collected[:n]


# Keep single-image wrapper for backward compat
def find_image(title: str, preferred_url: "str | None" = None) -> "bytes | None":
    imgs = find_images(title, preferred_url=preferred_url, n=1)
    return imgs[0] if imgs else None


# ---------------------------------------------------------------------------
# 6. Generate post image (single card — no carousel)
# ---------------------------------------------------------------------------

def generate_post_image(
    headline: str,
    category: str,
    image_bytes: "bytes | None",
    slide_index: int = 0,
) -> "str | None":
    """
    Generate a single magazine-cover post card using create_post.py.
    slide_index is appended to the filename so carousel slides don't collide.
    Returns the file path, or None on failure.
    """
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from create_post import create_post  # noqa: PLC0415
    except Exception as exc:
        log.error("Could not import create_post: %s", exc)
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_s{slide_index:02d}" if slide_index else ""
    tmp_bg: "str | None" = None

    if image_bytes:
        tmp_bg = str(OUTPUT_DIR / f"_tmp_bg_{ts}{suffix}.jpg")
        with open(tmp_bg, "wb") as f:
            f.write(image_bytes)

    out_path = str(OUTPUT_DIR / f"post_{ts}{suffix}.png")
    try:
        create_post(
            headline=headline,
            category=category,
            image_path=tmp_bg,
            size="portrait",
            output_path=out_path,
            focal_point="center",
        )
        log.info("Generated post card: %s", out_path)
        return out_path
    except Exception as exc:
        log.error("Post card generation failed: %s", exc, exc_info=True)
        return None
    finally:
        if tmp_bg:
            try:
                os.unlink(tmp_bg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 6b. Carousel generator (multiple branded slides, one per image)
# ---------------------------------------------------------------------------

def generate_carousel(
    headline: str,
    category: str,
    image_bytes_list: "list[bytes]",
    max_slides: int = 4,
) -> "list[str]":
    """
    Generate one branded post card per image (up to max_slides).
    Each card uses the same headline/category overlay on a different photo.
    Falls back to a single dark-background placeholder card if no images.

    Returns a list of file paths (at least 1 on success, empty on error).
    """
    if not image_bytes_list:
        # No images — one clean dark-background branded card
        log.info("No images — generating dark placeholder card.")
        path = generate_post_image(headline, category, None)
        return [path] if path else []

    paths: list[str] = []
    for i, img_bytes in enumerate(image_bytes_list[:max_slides], start=1):
        path = generate_post_image(headline, category, img_bytes, slide_index=i)
        if path:
            paths.append(path)
            log.info("Slide %d/%d: %s", i, min(len(image_bytes_list), max_slides), path)
        else:
            log.warning("Slide %d failed to generate — skipping.", i)
    return paths


# ---------------------------------------------------------------------------
# 7. Post to Instagram via instagrapi
# ---------------------------------------------------------------------------

def post_to_instagram(image_paths: "list[str] | str", caption: str) -> bool:
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
    # Allow session-only mode: if the session file exists we don't need env creds
    # (the session file was generated locally and contains auth cookies).
    has_session = INSTAGRAM_SESSION_FILE.exists()
    if not has_session and (not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD):
        log.error("No instagram_session.json and INSTAGRAM credentials not set.")
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

    # ── Convert all PNG slides to JPEG (Instagram requirement) ───────────────
    import tempfile as _tmpfile
    from PIL import Image as _Image
    from pathlib import Path as _Path

    if isinstance(image_paths, str):
        image_paths = [image_paths]

    jpeg_paths: list[str] = []
    tmp_jpegs:  list[str] = []
    for png_path in image_paths:
        try:
            with _Image.open(png_path) as img:
                w, h = img.size
                # Safety net: crop from bottom if taller than 4:5
                max_h = int(w * 5 / 4)
                if h > max_h:
                    img = img.crop((0, 0, w, max_h))
                _tmp_fd, _tmp_path = _tmpfile.mkstemp(suffix=".jpg", dir=str(OUTPUT_DIR))
                import os as _os; _os.close(_tmp_fd)
                img.convert("RGB").save(_tmp_path, "JPEG", quality=95)
                jpeg_paths.append(_tmp_path)
                tmp_jpegs.append(_tmp_path)
        except Exception as exc:
            log.warning("JPEG conversion failed for %s: %s — using original", png_path, exc)
            jpeg_paths.append(png_path)

    log.info("Prepared %d JPEG slide(s) for upload.", len(jpeg_paths))

    # ── Monkey-patch for Instagram's updated configure response ──────────────
    from instagrapi.mixins import media as _media_mixin  # noqa: PLC0415
    _original_extract = _media_mixin.MediaMixin._extract_configured_media_or_raise

    def _patched_extract(self, configured, exception_cls, context):
        last = self.last_json if isinstance(self.last_json, dict) else {}
        cfg  = configured    if isinstance(configured,    dict) else {}
        if last.get("status") == "ok" or cfg.get("status") == "ok":
            import time as _t; _t.sleep(2)
            try:
                medias = self.user_medias_v1(self.user_id, amount=1)
                if medias:
                    log.info("Fetched latest media after configure: %s", medias[0].pk)
                    return medias[0]
            except Exception as _fe:
                log.warning("Could not fetch latest media: %s", _fe)
            from instagrapi.types import Media as _Media
            return _Media(pk="0", id="0", code="", media_type=1,
                         taken_at=__import__("datetime").datetime.now())
        return _original_extract(self, configured, exception_cls, context)

    _media_mixin.MediaMixin._extract_configured_media_or_raise = _patched_extract

    # ── Upload ────────────────────────────────────────────────────────────────
    import time as _time
    _time.sleep(1)

    def _cleanup():
        for p in tmp_jpegs:
            try:
                _os.unlink(p)
            except Exception:
                pass

    try:
        if len(jpeg_paths) == 1:
            log.info("Uploading single photo …")
            media = cl.photo_upload(
                path=jpeg_paths[0],
                caption=caption,
                extra_data={"custom_accessibility_caption": "", "like_and_view_counts_disabled": 0},
            )
        else:
            log.info("Uploading carousel (%d slides) …", len(jpeg_paths))
            media = cl.album_upload(
                paths=jpeg_paths,
                caption=caption,
            )

        if media.code:
            log.info("Posted! Media ID: %s  URL: https://www.instagram.com/p/%s/",
                     media.pk, media.code)
        else:
            log.info("Posted! (media details unavailable — check @footyculturehq)")
        _cleanup()
        return True

    except Exception as exc:
        log.error("Instagram upload failed: %s", exc, exc_info=True)
        _cleanup()
        return False


# ---------------------------------------------------------------------------
# Max posts per day guard
# ---------------------------------------------------------------------------

MAX_POSTS_PER_DAY = 2

def _posts_today(posted: list[dict]) -> int:
    """Count how many posts were made in the last 24 hours."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    count = 0
    for p in posted:
        try:
            ts_str = p.get("posted_at", "")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                count += 1
        except Exception:
            pass
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Footy Culture HQ Instagram pipeline")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate the card locally but do NOT post to Instagram.",
    )
    parser.add_argument(
        "--force-url", metavar="URL",
        help="Force the pipeline to use this article URL instead of scraping for stories. "
             "Useful for testing a specific article. Implies --dry-run unless combined with live run.",
    )
    parser.add_argument(
        "--force-title", metavar="TITLE", default=None,
        help="Override the headline when using --force-url.",
    )
    args = parser.parse_args()
    dry_run: bool = args.dry_run

    log.info("=== Footy Culture HQ pipeline starting%s ===",
             " [DRY RUN]" if dry_run else "")

    # ── Force-URL shortcut: test a specific article without full scrape ───────
    if args.force_url:
        force_url   = args.force_url.strip()
        force_title = (args.force_title or force_url.split("/")[-1]
                       .replace("-", " ").replace(".html", "").title())
        log.info("FORCE URL mode: %s  title=%r  dry_run=%s", force_url, force_title, dry_run)
        category       = pick_category(force_title)
        raw_headline   = format_headline(force_title)
        hype_headline  = inject_hype(raw_headline, category)
        caption        = build_caption(force_title, category)
        log.info("Category: %s  Headline: %r", category, hype_headline)
        images_bytes   = find_images(force_title, article_url=force_url, n=3)
        slide_paths    = generate_carousel(hype_headline, category, images_bytes)
        if not slide_paths:
            log.error("Card generation failed.")
            return
        log.info("Generated %d slide(s): %s", len(slide_paths), slide_paths)
        if dry_run:
            log.info("[DRY RUN] Skipping Instagram post. Cards: %s", slide_paths)
        elif not INSTAGRAM_SESSION_FILE.exists() and (not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD):
            log.warning("No session file and no INSTAGRAM credentials — skipping post.")
        else:
            success = post_to_instagram(slide_paths, caption)
            if success:
                posted = _load_posted()
                posted.append({
                    "id": force_url.split("/")[-1].replace(".html", ""),
                    "title": force_title,
                    "url": force_url,
                    "posted_at": datetime.now(tz=timezone.utc).isoformat(),
                    "tag": category,
                })
                _save_posted(posted)
                log.info("Marked as posted.")
            else:
                log.error("Instagram post failed.")
        return

    # ── Load history ─────────────────────────────────────────────────────────
    posted = _load_posted()
    log.info("Stories already posted: %d", len(posted))

    # ── Max posts per day guard ───────────────────────────────────────────────
    today_count = _posts_today(posted)
    log.info("Posts in last 24h: %d / %d max", today_count, MAX_POSTS_PER_DAY)
    if not dry_run and today_count >= MAX_POSTS_PER_DAY:
        log.info("Daily post limit reached (%d). Exiting.", MAX_POSTS_PER_DAY)
        return

    # ── Scrape all sources ────────────────────────────────────────────────────
    fh_stories     = scrape_stories()
    nitter_stories = scrape_nitter()
    rss_stories    = scrape_rss_feeds()

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

    # ── Cross-source confirmation ─────────────────────────────────────────────
    # If the same ENTITY (club/player/boot) appears in stories from 2+ different
    # sources within our window, mark all those stories as cross_source_confirmed.
    # We fingerprint by extracting the most specific noun from the title.
    def _story_fingerprint(title: str) -> str:
        """Return a short lower-case key representing the main entity."""
        t = title.lower()
        # Remove common filler words
        filler = re.compile(
            r"\b(kit|boot|boots|shoe|shoes|jersey|shirt|away|home|third|new|"
            r"leaked|leak|spotted|official|revealed?|confirmed|launch|drop|"
            r"release|season|colou?rway|picture|photo|image)\b"
        )
        key = filler.sub("", t)
        key = re.sub(r"[^a-z0-9 ]", " ", key)
        key = re.sub(r"\s+", " ", key).strip()
        return key[:40]   # first 40 chars of normalised title

    source_map: dict[str, set[str]] = {}   # fingerprint → set of sources
    fp_map:     dict[str, str]      = {}   # story_id → fingerprint

    for s in unique:
        fp  = _story_fingerprint(s["title"])
        src = s.get("source", "FootyHeadlines")
        fp_map[s["id"]] = fp
        source_map.setdefault(fp, set()).add(src)

    confirmed_fps = {fp for fp, srcs in source_map.items() if len(srcs) >= 2}

    for s in unique:
        fp = fp_map.get(s["id"], "")
        if fp in confirmed_fps:
            s["cross_source_confirmed"] = True
            log.info("  ✓ Cross-source confirmed: %r (sources: %s)",
                     s["title"][:60], ", ".join(source_map[fp]))

    # ── Score + filter ────────────────────────────────────────────────────────
    posted_ids = {p.get("id") for p in posted}
    candidates: list[dict] = []
    for s in unique:
        if s["id"] in posted_ids:
            continue
        score, reason = score_story(s)
        cat = pick_category(s["title"])
        log.info("  [score=%d/10 age=%d cat=%-12s] %s  (%s)",
                 score, s["age_days"], cat, s["title"][:65], reason)
        if score >= 7:
            candidates.append({**s, "_score": score})
        else:
            log.info("    → SKIPPED (score %d < 7)", score)

    # Sort: highest score first; break ties by freshness
    candidates.sort(key=lambda s: (-s["_score"], s["age_days"]))

    if not candidates:
        log.info("No stories scored ≥7. Nothing to post this run.")
        return

    story = candidates[0]
    log.info(
        "Selected story (score=%d): %r  source=%s  age=%d days",
        story["_score"],
        story["title"],
        story.get("source", "FootyHeadlines"),
        story["age_days"],
    )

    # ── Prepare content ───────────────────────────────────────────────────────
    category = pick_category(story["title"])
    raw_headline = format_headline(story["title"])
    hype_headline = inject_hype(raw_headline, category)
    caption = build_caption(story["title"], category)

    log.info("Category: %s", category)
    log.info("Headline (hype): %r", hype_headline)
    log.info("Caption:\n%s", caption)

    # ── Find up to 3 accurate images for carousel ────────────────────────────
    preferred_img_url: "str | None" = story.get("tweet_image")
    images_bytes = find_images(
        story["title"],
        preferred_url=preferred_img_url,
        article_url=story.get("url"),
        n=3,
    )

    if not images_bytes:
        log.warning("No images found — will use dark placeholder background.")

    # ── Generate carousel (1 card per image, or 1 dark placeholder) ──────────
    slide_paths = generate_carousel(hype_headline, category, images_bytes)

    if not slide_paths:
        log.error("Card generation failed. Aborting.")
        return

    log.info("Generated %d slide(s): %s", len(slide_paths), slide_paths)

    # ── Post to Instagram (or skip if dry-run) ────────────────────────────────
    if dry_run:
        log.info("[DRY RUN] Skipping Instagram post. Cards: %s", slide_paths)
    elif not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
        log.warning("INSTAGRAM_USERNAME/PASSWORD not set — skipping Instagram post.")
    else:
        success = post_to_instagram(slide_paths, caption)
        if not success:
            log.error("Instagram post failed. Not marking story as posted.")
            return

    # ── Record success ────────────────────────────────────────────────────────
    if not dry_run:
        posted.append({
            "id": story["id"],
            "title": story["title"],
            "url": story["url"],
            "posted_at": datetime.now(tz=timezone.utc).isoformat(),
            "tag": category,
        })
        _save_posted(posted)
        log.info("Marked %r as posted. Total posted: %d", story["id"], len(posted))

    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
