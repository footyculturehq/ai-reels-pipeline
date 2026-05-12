"""
create_story.py — Instagram Story card generator with poll overlay.

Generates a 1080×1920 (9:16) Story card:
  - Full-bleed blurred + darkened feed post image as background
  - Scaled feed post image (88% width) with rounded corners + drop shadow,
    placed in the upper portion of the frame
  - Short hook text above the post image (e.g. "COP OR DROP?")
  - Styled poll card below the image: question + two colour-coded option buttons
  - @footyculturehq handle at the bottom

The poll overlay is fully rendered — no native IG sticker API needed.
Use the output JPEG as-is for a photo Story post (instagrapi photo_upload_to_story).

Usage:
    from create_story import create_story, generate_poll, pick_hook

    poll = generate_poll("BOOT LAUNCH", {"title": "Adidas Predator 2026 Revealed"})
    hook = pick_hook("BOOT LAUNCH")
    path = create_story(
        post_image_path="output/post_xxx.jpg",
        hook=hook,
        poll_question=poll["question"],
        poll_options=poll["options"],
    )
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
    poll_question: str,
    poll_options: list,
    output_path: str = None,
) -> str:
    """
    Render a 1080×1920 Story card.

    Layout (top→bottom):
      280px   hook text (e.g. "COP OR DROP?")
      ~680px  feed post image at 88% width, rounded corners, drop shadow
       40px   gap
      260px   poll card: question + two colour-coded option buttons
       …      spacer
      100px   handle

    Returns the path to the saved JPEG Story image.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Load and crop feed post image ─────────────────────────────────────────
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
    bg = ImageEnhance.Brightness(bg).enhance(0.26)   # very dark — content pops

    canvas = bg.convert("RGBA")

    # ── Feed post image: rounded corners + drop shadow ────────────────────────
    post_w  = int(STORY_W * 0.88)
    post_h  = int(post_w * feed_img.height / feed_img.width)
    post_scaled   = feed_img.resize((post_w, post_h), Image.LANCZOS)
    post_rounded  = _add_rounded_corners(post_scaled, radius=28)
    post_shadowed = _add_drop_shadow(post_rounded, offset=(0, 20), blur=32, opacity=0.50)

    # Padding for the drop shadow layer
    shadow_pad = 32 * 2                            # blur * 2 in _add_drop_shadow
    hook_area  = 240                               # pixels reserved above image for hook
    post_paste_x = (STORY_W - post_shadowed.width) // 2
    post_paste_y = hook_area
    canvas.paste(post_shadowed, (post_paste_x, post_paste_y), post_shadowed)

    # ── Hook text ─────────────────────────────────────────────────────────────
    draw      = ImageDraw.Draw(canvas)
    hook_font = _sfont(76, "headline")
    hook_str  = hook.upper()
    hook_w    = _tw(draw, hook_str, hook_font)
    hook_x    = (STORY_W - hook_w) // 2
    hook_y    = 80
    # Text shadow for legibility
    draw.text((hook_x + 3, hook_y + 3), hook_str, font=hook_font,
              fill=(0, 0, 0, 170))
    draw.text((hook_x,     hook_y),     hook_str, font=hook_font,
              fill=(255, 255, 255, 255))

    # ── Poll card ─────────────────────────────────────────────────────────────
    poll_card_top = post_paste_y + post_shadowed.height + 38
    poll_card_h   = 260
    poll_card_w   = int(STORY_W * 0.88)
    poll_card_x   = (STORY_W - poll_card_w) // 2

    poll_layer = Image.new("RGBA", (STORY_W, STORY_H), (0, 0, 0, 0))
    pd         = ImageDraw.Draw(poll_layer)

    # Card background: white, semi-transparent, rounded
    pd.rounded_rectangle(
        [(poll_card_x, poll_card_top),
         (poll_card_x + poll_card_w, poll_card_top + poll_card_h)],
        radius=22, fill=(255, 255, 255, 228),
    )

    # Poll question (black text, max 2 lines)
    q_font  = _sfont(40, "ui")
    q_text  = poll_question.upper()
    q_max_w = poll_card_w - 48
    words   = q_text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        test = (cur + " " + word).strip()
        if _tw(pd, test, q_font) <= q_max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    q_lines = lines[:2]

    q_y = poll_card_top + 20
    for line in q_lines:
        lw = _tw(pd, line, q_font)
        pd.text(((STORY_W - lw) // 2, q_y), line, font=q_font,
                fill=(10, 10, 10, 255))
        q_y += int(40 * 1.2)

    # Option buttons (two side-by-side, colour-coded)
    opt_top  = poll_card_top + poll_card_h - 95
    opt_h    = 66
    opt_gap  = 18
    opt_w    = (poll_card_w - opt_gap * 3) // 2
    opt_font = _sfont(38, "ui")

    BLUE   = (41, 109, 247, 255)   # option A
    ORANGE = (255, 88, 18, 255)    # option B

    for i, opt_text in enumerate(poll_options[:2]):
        ox     = poll_card_x + opt_gap + i * (opt_w + opt_gap)
        oy     = opt_top
        colour = BLUE if i == 0 else ORANGE
        pd.rounded_rectangle([(ox, oy), (ox + opt_w, oy + opt_h)],
                              radius=14, fill=colour)
        label = opt_text.upper()
        tw    = _tw(pd, label, opt_font)
        pd.text(
            (ox + (opt_w - tw) // 2, oy + (opt_h - 38) // 2 - 2),
            label, font=opt_font, fill=(255, 255, 255, 255),
        )

    canvas = Image.alpha_composite(canvas, poll_layer)

    # ── Handle ────────────────────────────────────────────────────────────────
    draw     = ImageDraw.Draw(canvas)
    hdl_font = _sfont(34, "ui_light")
    hdl_text = "@footyculturehq"
    hdl_w    = _tw(draw, hdl_text, hdl_font)
    draw.text(
        ((STORY_W - hdl_w) // 2, STORY_H - 120),
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
