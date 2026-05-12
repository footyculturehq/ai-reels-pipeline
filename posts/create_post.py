"""
Footy Culture HQ — Post Card Generator
Magazine-cover quality. Matches @soccerbible / @footyheadlines aesthetic.

Design spec (v3):
  - Full-bleed hero image, no borders
  - Source image: saturation +15%, brightness +5% so hero details pop
  - Top vignette: SHORT (50px) semi-transparent fade — just enough to read the wordmark,
    not so dark it muddies a product with a naturally dark background
  - Bottom gradient: 58% → bottom, max 72% black
  - Top-left: "FOOTY CULTURE" clean text only — no icon, thin weight, white 70%
  - Above headline: category tag — SOLID WHITE BOX, BLACK TEXT (premium pill)
  - Headline: Anton font, ALL CAPS, 120→58px auto-sized, max 2 lines (3 at 58px)
  - Bottom padding: 100px so headline breathes above the edge
  - Bottom-right: "@footyculturehq" handle, white 55% opacity
"""

import argparse, os, re, sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageEnhance, ImageFilter
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageEnhance, ImageFilter

SCRIPT_DIR = Path(__file__).parent
OUT_DIR    = SCRIPT_DIR / "output"
FONT_DIR   = SCRIPT_DIR / "fonts"

WHITE       = (255, 255, 255)
PITCH_BLACK = (0,   0,   0)

# Instagram 4:5 portrait
SIZES = {"portrait": (1080, 1350), "square": (1080, 1080)}

# Bottom gradient: starts at 58% down, max 72% opacity
GRADIENT_START_FRAC = 0.58
OVERLAY_MAX_ALPHA   = int(255 * 0.72)

# Top vignette: short semi-transparent fade just for wordmark legibility
TOP_VIGN_H     = 110          # gradient covers top 110px
TOP_VIGN_MAX_A = 180          # max 71% — does NOT black out the image

CATEGORY_LABELS = {
    "KIT DROP":    "KIT DROP",
    "BOOT LAUNCH": "BOOT LAUNCH",
    "SIGNING":     "SIGNING",
    "COLLAB":      "COLLAB",
    "VAULT":       "VAULT",
    "LEAKED":      "LEAKED",
    "SPOTTED":     "SPOTTED",
    "FOOTBALL":    "FOOTBALL",
}

# Category → best canvas size.
# Boots are wide → square frames them without heavy crop.
# Kits / signings / collabs → tall portrait shows more of the product.
CATEGORY_SIZE = {
    "BOOT LAUNCH": "square",
    "SPOTTED":     "square",   # on-pitch / training shots are often wide
    "KIT DROP":    "portrait",
    "SIGNING":     "portrait",
    "COLLAB":      "portrait",
    "VAULT":       "portrait",
    "LEAKED":      "portrait",
    "FOOTBALL":    "portrait",
}


# ---------------------------------------------------------------------------
# Font loader
# ---------------------------------------------------------------------------

def _font(size: int, style: str = "headline") -> ImageFont.FreeTypeFont:
    """
    headline → Anton (bold condensed)
    ui       → Barlow Condensed Bold / Arial Bold fallback
    ui_light → Barlow Condensed SemiBold / Arial fallback (wordmark)
    """
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
    else:  # ui — labels, handles
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


def _tw(draw, text, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw, text, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


# ---------------------------------------------------------------------------
# Headline word-wrapper with auto font-size
# ---------------------------------------------------------------------------

def _wrap_headline(draw, text: str, max_w: int, max_lines: int = 2
                   ) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """
    Find the largest Anton size (120→58px) where the text fits in ≤ max_lines.
    Falls back to 3 lines at 58px for very long headlines.
    """
    text = text.upper()
    for size in range(120, 52, -6):
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

    # Last resort: 3 lines at 58px
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
# Letterbox helpers
# ---------------------------------------------------------------------------

def _detect_dark_background(photo: Image.Image, threshold: float = 0.22) -> bool:
    """
    Returns True if the image has a predominantly dark background.
    Samples 6×6 crops from each corner — typically where the bg is exposed on
    product shots (boots/kits on white/black studio backgrounds).
    """
    try:
        rgb = photo.convert("RGB")
        w, h = rgb.size
        r = min(40, w // 6, h // 6)
        corners = [
            (0, 0, r, r),           (w - r, 0, w, r),
            (0, h - r, r, h),       (w - r, h - r, w, h),
        ]
        total, count = 0.0, 0
        for box in corners:
            region = rgb.crop(box).resize((6, 6), Image.LANCZOS)
            for cy in range(6):
                for cx in range(6):
                    px = region.getpixel((cx, cy))
                    total += (px[0] + px[1] + px[2]) / (3 * 255)
                    count += 1
        return (total / count) < threshold if count else False
    except Exception:
        return False


def _add_feathered_edges(img: Image.Image, feather_radius: int = 18) -> Image.Image:
    """
    Returns RGBA image — edges fade to transparent over feather_radius pixels.
    Existing alpha (PNG cutouts) is multiplied so cutout shapes are preserved.

    How it works:
      1. Draw a solid-white rectangle inset by feather_radius on all sides.
      2. GaussianBlur spreads the white outward, creating a 0→255 gradient mask.
      3. Multiply the gradient mask with any existing alpha channel.
    """
    img_rgba = img.convert("RGBA")
    w, h = img_rgba.size
    r = max(1, feather_radius)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([r, r, w - r - 1, h - r - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=r * 0.65))
    # Multiply preserves any pre-existing transparent regions (PNG cutouts)
    combined = ImageChops.multiply(img_rgba.getchannel("A"), mask)
    img_rgba.putalpha(combined)
    return img_rgba


# ---------------------------------------------------------------------------
# Letterbox-with-blur compositor
# ---------------------------------------------------------------------------

def _letterbox_blur(
    photo: Image.Image,
    target_w: int,
    target_h: int,
    blur_radius: int = 60,
    darken_factor: float = 0.55,
    product_scale: float = 0.82,
    feather_edges: int = 18,
) -> Image.Image:
    """
    Frame a product image into (target_w × target_h) without cropping it.

    Background  = the same image, heavily blurred + darkened + desaturated.
                  Gives a "studio backdrop" feel that matches the product's
                  colour palette automatically.
    Foreground  = the full product, scaled to fit, feathered edges so it blends
                  smoothly into the backdrop.  PNGs with existing transparency
                  have their cutout preserved; the feather just softens cut edges.

    Dark-bg detection: if the source corners are near-black (metallic/studio
    render with a dark background) the backdrop darken_factor is pushed lower
    so the seam between fg and bg is invisible.

    Returns a composited RGB Image ready to paste onto the canvas.
    """
    has_alpha = photo.mode == "RGBA"

    # ── Match backdrop darkness to source ────────────────────────────────────
    # Products on dark backgrounds (black studio renders, iridescent boots)
    # need a dark backdrop — otherwise the letterbox seam is clearly visible.
    if _detect_dark_background(photo):
        darken_factor = min(darken_factor, 0.28)

    # ── Background: blur & darken (always work in RGB) ────────────────────────
    bg_ratio  = photo.width / photo.height
    tgt_ratio = target_w / target_h

    if bg_ratio > tgt_ratio:
        new_h = target_h
        new_w = int(new_h * bg_ratio)
    else:
        new_w = target_w
        new_h = int(new_w / bg_ratio)

    bg = photo.convert("RGB").copy().resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    bg   = bg.crop((left, top, left + target_w, top + target_h))

    bg = bg.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    bg = ImageEnhance.Brightness(bg).enhance(darken_factor)
    bg = ImageEnhance.Color(bg).enhance(0.65)          # desaturate bg slightly

    # ── Foreground: resize to fit (preserve source mode for RGBA PNGs) ────────
    fg_ratio = photo.width / photo.height

    if fg_ratio >= 1:
        # Wide / landscape (boots, balls) → constrain by width
        new_fg_w = int(target_w * product_scale)
        new_fg_h = int(new_fg_w / fg_ratio)
        # Safety: if scaled height is too tall, constrain by height instead
        if new_fg_h > int(target_h * product_scale):
            new_fg_h = int(target_h * product_scale)
            new_fg_w = int(new_fg_h * fg_ratio)
    else:
        # Tall / portrait (kits, jackets) → constrain by height, leave text room
        new_fg_h = int(target_h * product_scale * 0.75)
        new_fg_w = int(new_fg_h * fg_ratio)

    fg = photo.copy().resize((new_fg_w, new_fg_h), Image.LANCZOS)

    # Trim top 9%: removes source URL watermarks baked into the top-right corner
    fg_trim = int(new_fg_h * 0.09)
    fg = fg.crop((0, fg_trim, new_fg_w, new_fg_h))
    new_fg_h -= fg_trim

    # ── Feathered edges ───────────────────────────────────────────────────────
    # PNGs with a cutout alpha already have transparency; use half the feather
    # radius so the product boundary stays sharp.  JPEGs (no alpha) get the
    # full radius so dark/light edges blend into the blurred backdrop.
    radius = feather_edges // 2 if has_alpha else feather_edges
    fg = _add_feathered_edges(fg, feather_radius=radius)
    # fg is now always RGBA after feathering

    # ── Composite ────────────────────────────────────────────────────────────
    paste_x = (target_w - new_fg_w) // 2
    paste_y = int((target_h - new_fg_h) * 0.30)

    result = bg.convert("RGB")
    result.paste(fg, (paste_x, paste_y), fg)   # RGBA fg → uses alpha as mask
    return result


# ---------------------------------------------------------------------------
# Main card generator
# ---------------------------------------------------------------------------

def create_post(
    headline: str,
    category: str = "FOOTBALL",
    image_path: str = None,
    size: str = "auto",           # "auto" → resolve from CATEGORY_SIZE
    output_path: str = None,
    focal_point: str = "center",
) -> str:
    # ── Canvas size: auto-resolve from category, or use explicit value ─────────
    if size == "auto":
        size = CATEGORY_SIZE.get(category.upper(), "portrait")
    W, H = SIZES.get(size, SIZES["portrait"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # ── PHOTO: letterbox (boots/wide) or full-bleed crop (kits/portrait) ──────
    if image_path and os.path.exists(image_path):
        _raw = Image.open(image_path)
        # Preserve transparency for PNG cutouts (e.g. official brand press assets)
        _has_src_alpha = _raw.mode in ("RGBA", "LA") or (
            _raw.mode == "P" and "transparency" in _raw.info
        )
        photo = _raw.convert("RGBA" if _has_src_alpha else "RGB")

        # Boost colour/luminance — operate only on RGB channels to keep alpha intact
        _rgb = photo.convert("RGB")
        _rgb = ImageEnhance.Color(_rgb).enhance(1.18)       # +18% saturation
        _rgb = ImageEnhance.Brightness(_rgb).enhance(1.06)  # +6% brightness
        _rgb = ImageEnhance.Contrast(_rgb).enhance(1.04)    # +4% micro-contrast
        if _has_src_alpha:
            r, g, b = _rgb.split()
            photo = Image.merge("RGBA", (r, g, b, photo.getchannel("A")))
        else:
            photo = _rgb

        src_ar  = photo.width / photo.height
        tgt_ar  = W / H

        # Decision: wide source on portrait/square canvas → letterbox.
        # A landscape boot shot (ar ~1.5-2.0) on a portrait card (ar 0.8) would
        # lose most of the product to cropping; letterbox preserves the whole shoe.
        # Portrait/near-square sources on any canvas → full-bleed crop as before.
        use_letterbox = src_ar > 1.15 and tgt_ar <= 1.05

        if use_letterbox:
            composited = _letterbox_blur(photo, W, H,
                                         blur_radius=65,
                                         darken_factor=0.52,
                                         product_scale=0.84)
            canvas.paste(composited.convert("RGBA"), (0, 0))
        else:
            # Full-bleed crop (existing behaviour)
            if src_ar > tgt_ar:
                nh, nw = H, int(H * src_ar)
            else:
                nw, nh = W, int(W / src_ar)
            photo = photo.resize((nw, nh), Image.LANCZOS)
            ox    = (nw - W) // 2
            focal = (focal_point or "center").lower()
            oy    = 0 if focal == "top" else (nh - H if focal == "bottom" else (nh - H) // 2)
            photo = photo.crop((ox, oy, ox + W, oy + H))
            canvas.paste(photo.convert("RGBA"), (0, 0))
    else:
        draw_ph = ImageDraw.Draw(canvas)
        draw_ph.rectangle([(0, 0), (W, H)], fill=(15, 15, 15, 255))

    # ── TOP VIGNETTE — short fade for wordmark legibility only ────────────────
    # Semi-transparent (max 71%) — keeps the image visible at the top,
    # unlike the old fully-opaque band that was muddying dark-background shots.
    top_vign = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tv_draw  = ImageDraw.Draw(top_vign)
    for row in range(TOP_VIGN_H):
        t     = 1.0 - (row / TOP_VIGN_H)      # 1.0 at very top → 0 at bottom
        alpha = int(TOP_VIGN_MAX_A * (t ** 0.7))
        tv_draw.rectangle([(0, row), (W, row + 1)], fill=(0, 0, 0, alpha))
    canvas = Image.alpha_composite(canvas, top_vign)

    # ── TOP-RIGHT BRAND COVER — opaque black corner to bury any source URL ────
    # footyheadlines (and most sport-media CDNs) embed "WWW.SITE.COM" in the
    # top-right corner of every image.  A 220px wide × 60px tall solid-black
    # block + a 40px gradient left-edge fade erases it cleanly without killing
    # the hero image — the top vignette already darkens the very top anyway.
    TR_W = 260   # cover width (px) — enough for ~20-char URL at small font
    TR_H = 72    # cover height (px) — tall enough for 2-line URLs at any size
    tr_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tr_draw  = ImageDraw.Draw(tr_layer)
    # Solid core
    tr_draw.rectangle([(W - TR_W + 40, 0), (W, TR_H)], fill=(0, 0, 0, 255))
    # Left-edge fade (40px) so it blends into the vignette
    for col in range(40):
        fade_a = int(255 * (col / 40) ** 1.5)
        tr_draw.rectangle(
            [(W - TR_W + col, 0), (W - TR_W + col + 1, TR_H)],
            fill=(0, 0, 0, fade_a),
        )
    canvas = Image.alpha_composite(canvas, tr_layer)

    # ── BOTTOM GRADIENT (transparent → 72% black) ─────────────────────────────
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

    pad_x = 52
    pad_y = 44

    # ── TOP-LEFT: "FOOTY CULTURE" wordmark — clean text, no icon ─────────────
    wm_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wm_draw  = ImageDraw.Draw(wm_layer)
    wm_font  = _font(22, "ui_light")
    wm_col   = (255, 255, 255, 179)   # white 70%
    wm_draw.text((pad_x, pad_y), "FOOTY CULTURE", font=wm_font, fill=wm_col)
    canvas = Image.alpha_composite(canvas, wm_layer)
    draw = ImageDraw.Draw(canvas)

    # ── MEASURE HEADLINE ──────────────────────────────────────────────────────
    max_tw   = W - pad_x * 2
    hl_lines, hl_font = _wrap_headline(draw, headline, max_tw)
    hl_size  = hl_font.size
    line_h   = int(hl_size * 0.94)   # tight line-height

    # ── CATEGORY TAG ─────────────────────────────────────────────────────────
    cat_label  = CATEGORY_LABELS.get(category.upper(), category.upper())
    tag_font   = _font(21, "ui")
    tag_pad_x  = 16
    tag_pad_y  = 7
    tag_tw     = _tw(draw, cat_label, tag_font)
    tag_th     = _th(draw, cat_label, tag_font)
    tag_box_h  = tag_th + tag_pad_y * 2
    tag_box_w  = tag_tw + tag_pad_x * 2

    # ── HANDLE (bottom-right) ─────────────────────────────────────────────────
    hdl_font = _font(21, "ui")
    hdl_text = "@footyculturehq"
    hdl_tw   = _tw(draw, hdl_text, hdl_font)
    hdl_th   = _th(draw, hdl_text, hdl_font)

    # ── LAYOUT: anchor to bottom, stack upward ────────────────────────────────
    bottom_pad = 100          # extra breathing room above the bottom edge
    gap_hl_tag = 20           # gap between tag bottom and headline top
    gap_hl_hdl = 28           # gap between headline bottom and handle
    hl_block_h = len(hl_lines) * line_h

    hdl_y      = H - bottom_pad - hdl_th
    hl_end_y   = hdl_y - gap_hl_hdl
    hl_start_y = hl_end_y - hl_block_h
    tag_y      = hl_start_y - gap_hl_tag - tag_box_h

    # ── DRAW CATEGORY TAG — SOLID WHITE BOX, BLACK TEXT (premium) ────────────
    draw.rectangle(
        [(pad_x, tag_y), (pad_x + tag_box_w, tag_y + tag_box_h)],
        fill=WHITE,
    )
    bb = draw.textbbox((0, 0), cat_label, font=tag_font)
    draw.text(
        (pad_x + tag_pad_x - bb[0], tag_y + tag_pad_y - bb[1]),
        cat_label, font=tag_font, fill=PITCH_BLACK,
    )

    # ── DRAW HEADLINE (white, ALL CAPS, tight line-height) ────────────────────
    cur_y = hl_start_y
    for line in hl_lines:
        draw.text((pad_x, cur_y), line, font=hl_font, fill=WHITE)
        cur_y += line_h

    # ── HANDLE bottom-right, white 55% opacity ────────────────────────────────
    hdl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hdl_draw  = ImageDraw.Draw(hdl_layer)
    hdl_x     = W - pad_x - hdl_tw
    hdl_draw.text((hdl_x, hdl_y), hdl_text, font=hdl_font,
                  fill=(255, 255, 255, 140))   # white 55%
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
