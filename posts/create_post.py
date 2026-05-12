"""
Footy Culture HQ — Post Card Generator
Magazine-cover quality. Matches @soccerbible / @footyheadlines aesthetic.

Design spec:
  - Full-bleed hero image, no borders
  - Subtle dark gradient on bottom 35% (0% → 70% opacity) — image shows through
  - Top-left: "FOOTY CULTURE" wordmark, small, white 80% opacity
  - Above headline: category tag (KIT DROP / BOOT LAUNCH / SIGNING etc.)
    white outlined box, transparent fill
  - Headline: Anton font, ALL CAPS, 90-120px auto-sized, max 2 lines, white
  - Bottom-right: "@footyculturehq" handle, small, white 60% opacity
  - No neon, no boot icons, no FOOTY NEWS boxes, clean and minimal
"""

import argparse, os, re, sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = Path(__file__).parent
OUT_DIR    = SCRIPT_DIR / "output"
FONT_DIR   = SCRIPT_DIR / "fonts"

WHITE       = (255, 255, 255)
PITCH_BLACK = (0,   0,   0)
NEON_GREEN  = (0,  255, 102)   # brand green for boot icon

# Instagram 4:5 — generated at correct ratio so no cropping ever needed
SIZES = {"portrait": (1080, 1350), "square": (1080, 1080)}

# Gradient: bottom 35% fades from transparent → 70% black
GRADIENT_START_FRAC = 0.58   # gradient begins 58% down (covers bottom 42%)
OVERLAY_MAX_ALPHA   = int(255 * 0.72)   # 72% opacity at very bottom

# Category tag → display label
CATEGORY_LABELS = {
    "KIT DROP":     "KIT DROP",
    "BOOT LAUNCH":  "BOOT LAUNCH",
    "SIGNING":      "SIGNING",
    "COLLAB":       "COLLAB",
    "VAULT":        "VAULT",
    "LEAKED":       "LEAKED",
    "SPOTTED":      "SPOTTED",
    "FOOTBALL":     "FOOTBALL",
}

# ---------------------------------------------------------------------------
# Boot icon
# ---------------------------------------------------------------------------

# Normalised polygon points for a right-facing football boot silhouette.
# x ranges 0 → 1.0, y ranges 0 → ~0.90  (height is the bounding height).
_BOOT_PTS = [
    (0.00, 0.52),  # heel-back top
    (0.00, 0.27),  # upper-back
    (0.12, 0.09),  # collar
    (0.36, 0.00),  # vamp top
    (0.64, 0.00),  # toe upper
    (0.88, 0.08),  # toe outer upper
    (1.00, 0.28),  # toe tip
    (0.96, 0.60),  # toe outer lower
    (0.80, 0.80),  # toe-sole junction
    (0.44, 0.90),  # mid-sole
    (0.07, 0.90),  # heel-sole
    (0.00, 0.70),  # heel bottom
]
_STUD_XS = [0.12, 0.30, 0.52, 0.70]   # x-fractions for stud dots


def _draw_boot_icon(draw: "ImageDraw.ImageDraw", x: int, y: int, h: int) -> int:
    """
    Draw a small right-facing football boot at (x, y) with given height h.
    Returns the pixel width consumed so callers can position text after it.
    """
    s = h / 0.90          # scale: 0.90 norm-units = h pixels
    pts = [(x + px * s, y + py * s) for px, py in _BOOT_PTS]
    draw.polygon(pts, fill=NEON_GREEN)

    # Stud row just below the sole
    stud_r = max(1.5, s * 0.055)
    stud_y = y + 0.93 * s
    for sx_f in _STUD_XS:
        cx = x + sx_f * s
        draw.ellipse([cx - stud_r, stud_y - stud_r,
                      cx + stud_r, stud_y + stud_r], fill=NEON_GREEN)

    return int(s * 1.05) + 2   # total width consumed (incl. studs + tiny gap)


# ---------------------------------------------------------------------------
# Font loader
# ---------------------------------------------------------------------------

def _font(size: int, style: str = "headline") -> ImageFont.FreeTypeFont:
    """
    headline → Anton (bold condensed, all-caps feel)
    ui       → Barlow Condensed Bold (clean labels and handles)
    """
    if style == "headline":
        candidates = [
            str(FONT_DIR / "Anton-Regular.ttf"),
            str(FONT_DIR / "BebasNeue-Regular.ttf"),
            str(FONT_DIR / "BarlowCondensed-ExtraBold.ttf"),
            "C:/Windows/Fonts/impact.ttf",
            "C:/Windows/Fonts/ariblk.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:  # ui — labels, handles, wordmark
        candidates = [
            str(FONT_DIR / "BarlowCondensed-Bold.ttf"),
            str(FONT_DIR / "BarlowCondensed-SemiBold.ttf"),
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


def _tw(draw, text, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw, text, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def _tb(draw, text, font):
    """Return full textbbox (x0, y0, x1, y1)."""
    return draw.textbbox((0, 0), text, font=font)


# ---------------------------------------------------------------------------
# Headline word-wrapper with auto font-size
# ---------------------------------------------------------------------------

def _wrap_headline(draw, text: str, max_w: int, max_lines: int = 2
                   ) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """
    Find the largest Anton size where the text fits in ≤ max_lines.
    Tries 120 → 58px in 6px steps, then falls back to 3 lines at 58px.
    Returns (wrapped_lines, font).
    """
    text = text.upper()
    for size in range(120, 52, -6):   # 120, 114, … 58px
        font = _font(size, "headline")
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if _tw(draw, test, font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
                if len(lines) >= max_lines:
                    break
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines:
            return lines, font

    # Last resort: allow 3 lines at 58px — still fits on the card
    font = _font(58, "headline")
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        if _tw(draw, test, font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3], font


# ---------------------------------------------------------------------------
# Main card generator
# ---------------------------------------------------------------------------

def create_post(
    headline: str,
    category: str = "FOOTBALL",    # KIT DROP / BOOT LAUNCH / SIGNING / LEAKED …
    image_path: str = None,
    size: str = "portrait",
    output_path: str = None,
    focal_point: str = "center",
) -> str:
    W, H = SIZES.get(size, SIZES["portrait"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # ── FULL-BLEED PHOTO ─────────────────────────────────────────────────────
    if image_path and os.path.exists(image_path):
        photo = Image.open(image_path).convert("RGB")
        ir, cr = photo.width / photo.height, W / H
        if ir > cr:
            nh, nw = H, int(H * ir)
        else:
            nw, nh = W, int(W / ir)
        photo = photo.resize((nw, nh), Image.LANCZOS)
        ox = (nw - W) // 2
        focal = (focal_point or "center").lower()
        oy = 0 if focal == "top" else (nh - H if focal == "bottom" else (nh - H) // 2)
        photo = photo.crop((ox, oy, ox + W, oy + H))
        canvas.paste(photo.convert("RGBA"), (0, 0))
    else:
        draw_ph = ImageDraw.Draw(canvas)
        draw_ph.rectangle([(0, 0), (W, H)], fill=(15, 15, 15, 255))

    # ── TOP VIGNETTE (kills source watermarks, frames the photo) ─────────────
    # Two-stage overlay at the top:
    #   Stage 1 (rows 0 – SOLID_H): near-fully opaque black — buries watermarks
    #   Stage 2 (SOLID_H – FADE_H): smooth gradient from opaque → transparent
    # Our "FOOTY CULTURE" + boot icon are rendered AFTER this overlay, so they
    # stay crisp white on the dark background.
    SOLID_H  = 90            # first 90px fully dark (where watermarks live)
    FADE_H   = int(H * 0.26) # gradient ends at 26% of card height
    SOLID_A  = 255           # fully opaque — kills ALL source watermarks

    top_vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tv_draw  = ImageDraw.Draw(top_vign)
    # Solid band
    tv_draw.rectangle([(0, 0), (W, SOLID_H)], fill=(0, 0, 0, SOLID_A))
    # Fade zone
    fade_zone = FADE_H - SOLID_H
    for row in range(fade_zone):
        t     = 1 - (row / fade_zone)            # 1 at top of fade → 0 at bottom
        alpha = int(SOLID_A * (t ** 1.2))
        tv_draw.rectangle(
            [(0, SOLID_H + row), (W, SOLID_H + row + 1)],
            fill=(0, 0, 0, alpha),
        )
    canvas = Image.alpha_composite(canvas, top_vign)

    # ── BOTTOM GRADIENT (0% → 72% black) ─────────────────────────────────────
    grad_start = int(H * GRADIENT_START_FRAC)
    grad_h     = H - grad_start
    overlay    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw    = ImageDraw.Draw(overlay)
    for row in range(grad_h):
        t     = row / grad_h
        alpha = int(OVERLAY_MAX_ALPHA * (t ** 0.55))
        ov_draw.rectangle(
            [(0, grad_start + row), (W, grad_start + row + 1)],
            fill=(0, 0, 0, alpha),
        )
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    pad_x  = 52
    pad_y  = 48

    # ── TOP-LEFT: small green boot icon + "FOOTY CULTURE" wordmark ───────────
    wm_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wm_draw  = ImageDraw.Draw(wm_layer)

    boot_h    = 22                                          # icon height px
    boot_w    = _draw_boot_icon(wm_draw, pad_x, pad_y + 4, boot_h)
    wm_font   = _font(26, "ui")
    wm_col    = (255, 255, 255, 204)                        # white 80%
    wm_draw.text((pad_x + boot_w + 8, pad_y), "FOOTY CULTURE",
                 font=wm_font, fill=wm_col)

    canvas = Image.alpha_composite(canvas, wm_layer)
    draw = ImageDraw.Draw(canvas)

    # ── MEASURE HEADLINE ──────────────────────────────────────────────────────
    max_tw   = W - pad_x * 2
    hl_lines, hl_font = _wrap_headline(draw, headline, max_tw)
    hl_size  = hl_font.size
    line_h   = int(hl_size * 0.92)   # tight line-height = 0.92

    # ── CATEGORY TAG ─────────────────────────────────────────────────────────
    cat_label = CATEGORY_LABELS.get(category.upper(), category.upper())
    tag_font  = _font(22, "ui")
    tag_pad_x, tag_pad_y = 14, 7
    tag_tw    = _tw(draw, cat_label, tag_font)
    tag_th    = _th(draw, cat_label, tag_font)
    tag_box_h = tag_th + tag_pad_y * 2
    tag_box_w = tag_tw + tag_pad_x * 2

    # ── HANDLE (bottom-right) ─────────────────────────────────────────────────
    hdl_font = _font(22, "ui")
    hdl_text = "@footyculturehq"
    hdl_tw   = _tw(draw, hdl_text, hdl_font)
    hdl_th   = _th(draw, hdl_text, hdl_font)

    # ── LAYOUT: anchor to bottom, stack upward ────────────────────────────────
    bottom_pad  = 54
    gap_hl_tag  = 18   # between tag box and headline
    gap_hl_hdl  = 22   # between last headline line and handle row
    hl_block_h  = len(hl_lines) * line_h

    hdl_y      = H - bottom_pad - hdl_th
    hl_end_y   = hdl_y - gap_hl_hdl
    hl_start_y = hl_end_y - hl_block_h
    tag_y      = hl_start_y - gap_hl_tag - tag_box_h

    # ── DRAW CATEGORY TAG — white outline, transparent fill ──────────────────
    outline_w = 2
    draw.rectangle(
        [(pad_x, tag_y),
         (pad_x + tag_box_w, tag_y + tag_box_h)],
        outline=WHITE,
        width=outline_w,
    )
    bb = draw.textbbox((0, 0), cat_label, font=tag_font)
    draw.text(
        (pad_x + tag_pad_x - bb[0], tag_y + tag_pad_y - bb[1]),
        cat_label, font=tag_font, fill=WHITE,
    )

    # ── DRAW HEADLINE (white, ALL CAPS, tight line-height) ────────────────────
    space_w = _tw(draw, " ", hl_font)
    cur_y   = hl_start_y
    for line in hl_lines:
        draw.text((pad_x, cur_y), line, font=hl_font, fill=WHITE)
        cur_y += line_h

    # ── HANDLE bottom-right, white 60% opacity ────────────────────────────────
    hdl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hdl_draw  = ImageDraw.Draw(hdl_layer)
    hdl_x     = W - pad_x - hdl_tw
    hdl_draw.text((hdl_x, hdl_y), hdl_text, font=hdl_font,
                  fill=(255, 255, 255, 153))   # white 60%
    canvas = Image.alpha_composite(canvas, hdl_layer)

    # ── SAVE ──────────────────────────────────────────────────────────────────
    result = canvas.convert("RGB")
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUT_DIR / f"post_{ts}.png")
    result.save(output_path, "PNG")
    kb = os.path.getsize(output_path) // 1024
    print(f"Saved: {output_path} ({kb}KB) {W}x{H}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--headline",  "-H", required=True)
    p.add_argument("--category",  "-t", default="FOOTBALL",
                   help="KIT DROP / BOOT LAUNCH / SIGNING / COLLAB / VAULT / LEAKED / SPOTTED")
    p.add_argument("--image",     "-i", default=None)
    p.add_argument("--size",      "-s", default="portrait", choices=["portrait", "square"])
    p.add_argument("--focal",     "-f", default="center",   choices=["center", "top", "bottom"])
    p.add_argument("--output",    "-o", default=None)
    args = p.parse_args()
    create_post(
        headline=args.headline,
        category=args.category,
        image_path=args.image,
        size=args.size,
        output_path=args.output,
        focal_point=args.focal,
    )


if __name__ == "__main__":
    main()
