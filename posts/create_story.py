"""
create_story.py — Instagram Story card generator (clean image for native poll sticker).

Generates a 1080×1920 (9:16) Story card:
  - Full-bleed blurred + darkened feed post image as background
  - Scaled feed post image (88% width) with rounded corners + drop shadow,
    centred in the frame
  - Short hook text above the post image (e.g. "COP OR DROP?")
  - @footyculturehq handle at the bottom

NO poll overlay is drawn — the interactive Instagram poll sticker is attached
by instagrapi when uploading (polls: [StoryPoll(...)]).  This lets users actually
tap the poll buttons on Stories rather than just looking at a picture of buttons.

Usage:
    from create_story import create_story, generate_poll, pick_hook

    poll = generate_poll("BOOT LAUNCH", {"title": "Adidas Predator 2026 Revealed"})
    hook = pick_hook("BOOT LAUNCH")
    path = create_story(
        post_image_path="output/post_xxx.jpg",
        hook=hook,
    )
    # pass poll["question"] and poll["options"] to post_story_to_instagram() instead
"""

import hashlib
import os
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

SCRIPT_DIR = Path(__file__).parent
OUT_DIR    = SCRIPT_DIR / "output"
FONT_DIR   = SCRIPT_DIR / "fonts"

STORY_W, STORY_H = 1080, 1920


# ---------------------------------------------------------------------------
# Font loader (mirrors create_post.py)
# ---------------------------------------------------------------------------

def _sfont(size: int, style: str = "headline") -> ImageFont.FreeTypeFont:
    if style == "headline":
        candidates = [
            str(FONT_DIR / "Anton-Regular.ttf"),
            str(FONT_DIR / "BebasNeue-Regular.ttf"),
            str(FONT_DIR / "BarlowCondensed-ExtraBold.ttf"),
            "C:/Windows/Fonts/impact.ttf",
            "C:/Windows/Fonts/ariblk.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    elif style == "ui_light":
        candidates = [
            str(FONT_DIR / "BarlowCondensed-SemiBold.ttf"),
            str(FONT_DIR / "BarlowCondensed-Bold.ttf"),
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    else:
        candidates = [
            str(FONT_DIR / "BarlowCondensed-Bold.ttf"),
            str(FONT_DIR / "Anton-Regular.ttf"),
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _tw(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _add_rounded_corners(img: Image.Image, radius: int = 28) -> Image.Image:
    """Clip image to a rounded rectangle; returns RGBA."""
    img = img.convert("RGBA")
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (w - 1, h - 1)],
                                           radius=radius, fill=255)
    img.putalpha(mask)
    return img


def _add_drop_shadow(
    img: Image.Image,
    offset: tuple = (0, 18),
    blur: int = 30,
    opacity: float = 0.50,
) -> Image.Image:
    """
    Composite a blurred black shadow behind the image.
    Returns RGBA with the shadow baked in and transparent canvas padding.
    """
    w, h     = img.size
    pad      = blur * 2
    canvas   = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_src   = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * opacity)))
    shadow_layer.paste(shadow_src, (pad + offset[0], pad + offset[1]))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=blur))

    canvas = Image.alpha_composite(canvas, shadow_layer)
    canvas.paste(img, (pad, pad), img)
    return canvas


# ---------------------------------------------------------------------------
# Poll template system
# ---------------------------------------------------------------------------

POLL_TEMPLATES: dict[str, list[dict]] = {
    "BOOT LAUNCH": [
        {"question": "Cop or drop?",                            "options": ["COP", "DROP"]},
        {"question": "Rate the colourway",                      "options": ["🔥 FIRE", "💀 MISS"]},
        {"question": "Would you lace these up Sunday league?",  "options": ["YES", "ONLY IF GOATED"]},
        {"question": "Better than last season's?",              "options": ["UPGRADE", "DOWNGRADE"]},
        {"question": "{brand} cooked with this one?",           "options": ["YES CHEF", "BURNT"],
         "needs": ["brand"]},
    ],
    "KIT DROP": [
        {"question": "Cop or pass?",                            "options": ["COP", "PASS"]},
        {"question": "Best kit of the season?",                 "options": ["YES", "NOT YET"]},
        {"question": "Would you wear this casually?",           "options": ["EVERY DAY", "MATCH ONLY"]},
        {"question": "Better than last year's?",                "options": ["GLOW UP", "STEP BACK"]},
        {"question": "{brand} cooking with this?",              "options": ["YES CHEF", "BURNT"],
         "needs": ["brand"]},
    ],
    "LEAKED": [
        {"question": "Ready for the official drop?",            "options": ["TAKE MY MONEY", "WAIT & SEE"]},
        {"question": "Cop on drop day?",                        "options": ["DAY ONE", "MAYBE NOT"]},
        {"question": "Better than expected?",                   "options": ["EXCEEDED", "DISAPPOINTED"]},
    ],
    "SIGNING": [
        {"question": "Baller or flop?",                         "options": ["BALLER", "FLOP"]},
        {"question": "Worth the fee?",                          "options": ["YES", "OVERPAID"]},
        {"question": "Will {player} succeed at {club}?",        "options": ["TOP SIGNING", "BIG MISTAKE"],
         "needs": ["player", "club"]},
    ],
    "COLLAB": [
        {"question": "Fire or forced?",                         "options": ["FIRE 🔥", "FORCED"]},
        {"question": "Cop for resell or wear?",                 "options": ["RESELL", "WEAR"]},
        {"question": "Best collab of the year?",                "options": ["TOP 3", "MID"]},
    ],
    "VAULT": [
        {"question": "Better than the original?",               "options": ["YES", "NEVER"]},
        {"question": "Glad it's back?",                         "options": ["FINALLY", "LEAVE IT DEAD"]},
        {"question": "Worth the reissue hype?",                 "options": ["YES", "OVERHYPED"]},
    ],
    "SPOTTED": [
        {"question": "Dropping soon?",                          "options": ["100%", "JUST A PE"]},
        {"question": "Cleanest boots on the pitch?",            "options": ["YES", "MID"]},
        {"question": "Would you cop these?",                    "options": ["DAY ONE", "WAIT FOR SALE"]},
    ],
    "FOOTBALL": [
        {"question": "Hot take — is this a W?",                 "options": ["BIG W", "BIG L"]},
        {"question": "Rate this drop",                          "options": ["🔥 HEAT", "❄️ ICE"]},
        {"question": "What do you think?",                      "options": ["MASSIVE", "OVERHYPED"]},
    ],
}

STORY_HOOKS: dict[str, list[str]] = {
    "BOOT LAUNCH":  ["COP OR DROP?", "RATE THEM", "FIRST LOOK", "VOTE BELOW", "HEAT OR TRASH?"],
    "KIT DROP":     ["RATE THE KIT", "COP OR PASS?", "BEST OF THE SEASON?", "VOTE NOW"],
    "LEAKED":       ["LEAKED 👀", "SPOTTED EARLY", "BEFORE THE OFFICIAL", "VOTE NOW"],
    "SIGNING":      ["BALLER OR FLOP?", "WORTH THE FEE?", "VOTE NOW"],
    "COLLAB":       ["THE COLLAB IS HERE", "FIRE OR FORCED?", "VOTE BELOW"],
    "VAULT":        ["BACK FROM THE DEAD", "BETTER THAN OG?", "VOTE NOW"],
    "SPOTTED":      ["SPOTTED IN TRAINING 👀", "DROPPING SOON?", "VOTE NOW"],
    "FOOTBALL":     ["WHAT YOU THINK?", "VOTE BELOW", "HOT TAKE?"],
}


def generate_poll(category: str, metadata: dict) -> dict:
    """
    Pick a poll template appropriate for the category and available metadata.
    Fills in template variables (brand, player, club) from metadata.
    Uses title hash for deterministic selection — stable across pipeline reruns.

    Returns dict with 'question' (str) and 'options' (list[str]).
    """
    cat       = category.upper()
    templates = POLL_TEMPLATES.get(cat, POLL_TEMPLATES["FOOTBALL"])

    # Filter to templates whose required fields are available
    usable = [
        t for t in templates
        if all(metadata.get(k) for k in t.get("needs", []))
    ]
    if not usable:
        usable = [t for t in templates if not t.get("needs")]

    # Deterministic choice keyed on title so the same story always gets the same poll
    title = metadata.get("title", cat)
    idx   = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(usable)
    chosen = usable[idx]

    question = chosen["question"]
    try:
        question = question.format(**{k: v for k, v in metadata.items() if isinstance(v, str)})
    except KeyError:
        pass

    return {"question": question, "options": chosen["options"]}


def pick_hook(category: str) -> str:
    """Return the first (most impactful) hook string for the given category."""
    hooks = STORY_HOOKS.get(category.upper(), ["VOTE BELOW"])
    return hooks[0]


# ---------------------------------------------------------------------------
# Story card renderer
# ---------------------------------------------------------------------------

def create_story(
    post_image_path: str,
    hook: str,
    output_path: str = None,
    # Legacy params kept for backward compat — ignored (poll is now an IG sticker)
    poll_question: str = None,
    poll_options: list = None,
) -> str:
    """
    Render a clean 1080×1920 Story background image.

    Layout (top→bottom):
      ~200px   hook text (e.g. "COP OR DROP?")
      ~centre  feed post card at 88% width, rounded corners + drop shadow
      bottom   @footyculturehq handle

    No poll overlay is drawn here — the interactive Instagram poll sticker is
    attached by instagrapi at upload time (pass polls=[StoryPoll(...)]).

    Returns the path to the saved JPEG Story image.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load feed post image ──────────────────────────────────────────────────
    feed_img = Image.open(post_image_path).convert("RGB")

    # ── Background: full-bleed blur + heavy darken ────────────────────────────
    bg_ar    = feed_img.width / feed_img.height
    story_ar = STORY_W / STORY_H
    if bg_ar > story_ar:
        new_h = STORY_H; new_w = int(new_h * bg_ar)
    else:
        new_w = STORY_W; new_h = int(new_w / bg_ar)
    bg = feed_img.copy().resize((new_w, new_h), Image.LANCZOS)
    ox = (new_w - STORY_W) // 2
    oy = (new_h - STORY_H) // 2
    bg = bg.crop((ox, oy, ox + STORY_W, oy + STORY_H))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=80))
    bg = ImageEnhance.Brightness(bg).enhance(0.26)
    canvas = bg.convert("RGBA")

    # ── Feed post card: rounded corners + drop shadow, centred vertically ─────
    post_w        = int(STORY_W * 0.88)
    post_h        = int(post_w * feed_img.height / feed_img.width)
    post_scaled   = feed_img.resize((post_w, post_h), Image.LANCZOS)
    post_rounded  = _add_rounded_corners(post_scaled, radius=28)
    post_shadowed = _add_drop_shadow(post_rounded, offset=(0, 20), blur=32, opacity=0.55)

    hook_area    = 220     # px above image reserved for hook text
    post_paste_x = (STORY_W - post_shadowed.width) // 2
    post_paste_y = hook_area
    canvas.paste(post_shadowed, (post_paste_x, post_paste_y), post_shadowed)

    # ── Hook text (large, centred, white with shadow) ─────────────────────────
    draw      = ImageDraw.Draw(canvas)
    hook_font = _sfont(80, "headline")
    hook_str  = hook.upper()
    hook_w    = _tw(draw, hook_str, hook_font)
    hook_x    = (STORY_W - hook_w) // 2
    hook_y    = 80
    for dx, dy, alpha in [(3, 3, 160), (0, 0, 255)]:
        col = (0, 0, 0, alpha) if dx else (255, 255, 255, 255)
        draw.text((hook_x + dx, hook_y + dy), hook_str, font=hook_font, fill=col)

    # ── @handle bottom-centre ─────────────────────────────────────────────────
    hdl_font = _sfont(36, "ui_light")
    hdl_text = "@footyculturehq"
    hdl_w    = _tw(draw, hdl_text, hdl_font)
    draw.text(
        ((STORY_W - hdl_w) // 2, STORY_H - 110),
        hdl_text, font=hdl_font, fill=(255, 255, 255, 140),
    )

    # ── Save ──────────────────────────────────────────────────────────────────
    result = canvas.convert("RGB")
    if not output_path:
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUT_DIR / f"story_{ts}.jpg")
    result.save(output_path, "JPEG", quality=95)
    kb = os.path.getsize(output_path) // 1024
    print(f"Story saved: {output_path} ({kb}KB) {STORY_W}×{STORY_H}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    p = argparse.ArgumentParser(description="Footy Culture Story card generator")
    p.add_argument("--post-image", "-i", required=True,
                   help="Path to the feed post card PNG/JPG")
    p.add_argument("--category",   "-c", default="BOOT LAUNCH")
    p.add_argument("--hook",       "-H", default=None,
                   help="Override hook text (default: auto from category)")
    p.add_argument("--question",   "-q", default=None)
    p.add_argument("--options",    "-o", nargs=2, default=["COP", "DROP"])
    p.add_argument("--output",           default=None)
    args = p.parse_args()

    hook = args.hook or pick_hook(args.category)
    if args.question:
        question = args.question
        options  = args.options
    else:
        poll     = generate_poll(args.category, {"title": args.category})
        question = poll["question"]
        options  = poll["options"]

    create_story(
        post_image_path=args.post_image,
        hook=hook,
        poll_question=question,
        poll_options=options,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
