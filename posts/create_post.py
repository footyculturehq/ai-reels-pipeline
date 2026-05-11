"""
Footy Culture HQ — Post Card Generator
Clean full-bleed image with semi-transparent text overlay at the bottom.

Design:
  - Full-bleed photo fills the entire card (no hard black section)
  - Light-to-dark gradient overlay at the bottom (~bottom 50%) — semi-transparent
    so the image bleeds through behind the text
  - NO top vignette / black bar
  - LEAKED / SPOTTED / BREAKING / DROPPED / NEWS badge
  - Large Barlow Condensed ExtraBold headline — key terms in acid green
  - @footyculturehq handle in acid green, bottom-left
  - Thin acid-green strip at the very bottom

Usage (single card):
  python posts/create_post.py \\
    --headline "Salah spotted in unreleased Nike Phantom GX3" \\
    --tag "SPOTTED" \\
    --image path/to/photo.jpg
"""

import argparse, os, re, sys
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

SCRIPT_DIR = Path(__file__).parent
OUT_DIR    = SCRIPT_DIR / "output"
FONT_DIR   = SCRIPT_DIR / "fonts"

ACID_GREEN  = (176, 255, 0)
PITCH_BLACK = (0, 0, 0)
WHITE       = (255, 255, 255)
HANDLE      = "@footyculturehq"

# Instagram 4:5 portrait — no cropping needed
SIZES = {"portrait": (1080, 1350), "square": (1080, 1080)}

# Overlay: how opaque the dark gradient gets at the very bottom of the card
# 0 = fully transparent, 255 = fully solid black.  ~190 = see-through but readable.
OVERLAY_MAX_ALPHA = 190

# Words auto-highlighted in acid green (case-insensitive)
AUTO_GREEN = {
    "nike", "adidas", "puma", "mizuno", "new balance", "nb", "umbro",
    "copa", "predator", "mercurial", "phantom", "tiempo", "superfly",
    "vapor", "future", "king", "tekela", "furon", "morelia",
    "exclusive", "unreleased", "leaked", "limited", "sold out",
    "dropped", "dropping", "spotted", "confirmed", "official",
    "premier league", "champions league", "world cup", "euro",
}

TAG_COLOURS = {
    "LEAKED":   ((255, 50,  50),  WHITE),   # red bg, white text
    "SPOTTED":  (ACID_GREEN,      PITCH_BLACK),
    "BREAKING": ((255, 50,  50),  WHITE),
    "DROPPED":  (ACID_GREEN,      PITCH_BLACK),
    "NEWS":     (WHITE,           PITCH_BLACK),
}


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

def _font(size: int, weight: str = "ExtraBold") -> ImageFont.FreeTypeFont:
    """Load best available font, falling back through system fonts."""
    weight_map = {
        "ExtraBold": ["BarlowCondensed-ExtraBold.ttf", "BarlowCondensed-Bold.ttf"],
        "Bold":      ["BarlowCondensed-Bold.ttf", "BarlowCondensed-SemiBold.ttf"],
        "Regular":   ["BarlowCondensed-SemiBold.ttf", "BarlowCondensed-Regular.ttf"],
    }
    candidates = []
    for fname in weight_map.get(weight, weight_map["ExtraBold"]):
        candidates.append(str(FONT_DIR / fname))

    # System fallbacks (Windows → Linux)
    candidates += [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _tw(draw: ImageDraw.Draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw: ImageDraw.Draw, text: str, font) -> int:
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


# ---------------------------------------------------------------------------
# Headline colour parsing
# ---------------------------------------------------------------------------

def _is_auto_green(word: str) -> bool:
    w = word.lower().strip(".,!?:;'\"")
    if re.match(r'^\d+(?:[.,]\d+)?[%£$€]?$', w):
        return True
    return w in AUTO_GREEN


def _parse(headline: str) -> list[tuple[str, bool]]:
    """Split headline into (token, is_green) pairs."""
    tokens = re.split(r'(\{[^}]+\})', headline)
    result = []
    for tok in tokens:
        if tok.startswith('{') and tok.endswith('}'):
            result.append((tok[1:-1], True))
        else:
            for part in re.split(r'(\s+)', tok):
                if not part:
                    continue
                if re.match(r'^\s+$', part):
                    result.append((part, False))
                else:
                    result.append((part, _is_auto_green(part)))
    return result


# ---------------------------------------------------------------------------
# Main card generator
# ---------------------------------------------------------------------------

def create_post(
    headline: str,
    caption: str = "",          # printed to terminal only — not rendered on card
    image_path: str = None,
    tag: str = "NEWS",
    size: str = "portrait",
    output_path: str = None,
    focal_point: str = "center",
    fit: bool = False,
    slide_num: int = 1,         # 1 = full headline card, 2+ = secondary (minimal text)
) -> str:
    W, H = SIZES.get(size, SIZES["portrait"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # ── FULL-BLEED PHOTO ─────────────────────────────────────────────────────
    if image_path and os.path.exists(image_path):
        photo = Image.open(image_path).convert("RGB")

        # Scale to cover full card
        ir, cr = photo.width / photo.height, W / H
        if ir > cr:   # photo is wider than card — scale by height, crop sides
            nh, nw = H, int(H * ir)
        else:         # photo is taller — scale by width, crop top/bottom
            nw, nh = W, int(W / ir)
        photo = photo.resize((nw, nh), Image.LANCZOS)

        # Crop anchor
        ox = (nw - W) // 2
        focal = (focal_point or "center").lower()
        if focal == "top":
            oy = 0
        elif focal == "bottom":
            oy = nh - H
        else:
            oy = (nh - H) // 2
        photo = photo.crop((ox, oy, ox + W, oy + H))
        canvas.paste(photo.convert("RGBA"), (0, 0))
    else:
        # Dark textured placeholder
        draw_ph = ImageDraw.Draw(canvas)
        draw_ph.rectangle([(0, 0), (W, H)], fill=(18, 18, 18, 255))

    # ── SEMI-TRANSPARENT BOTTOM GRADIENT ─────────────────────────────────────
    # Gradient starts at 35% from top (fully transparent) and reaches
    # OVERLAY_MAX_ALPHA at the very bottom. The image bleeds through.
    grad_start = int(H * 0.35)
    grad_h     = H - grad_start
    overlay    = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw    = ImageDraw.Draw(overlay)

    for row in range(grad_h):
        t     = row / grad_h                            # 0 → 1
        # ease-in curve: slow start, then accelerates — looks natural
        alpha = int(OVERLAY_MAX_ALPHA * (t ** 0.6))
        ov_draw.rectangle(
            [(0, grad_start + row), (W, grad_start + row + 1)],
            fill=(0, 0, 0, alpha),
        )

    canvas = Image.alpha_composite(canvas, overlay)

    draw = ImageDraw.Draw(canvas)

    strip_h = 6
    pad_x   = 48

    # ── SLIDE 2+ (secondary) — just background + handle + strip ──────────────
    if slide_num > 1:
        hf = _font(38, "Bold")
        draw.text((pad_x, H - strip_h - 20 - _th(draw, HANDLE, hf)),
                  HANDLE, font=hf, fill=ACID_GREEN)
        draw.rectangle([(0, H - strip_h), (W, H)], fill=ACID_GREEN)
        result = canvas.convert("RGB")
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(OUT_DIR / f"post_{ts}_s{slide_num}.png")
        result.save(output_path, "PNG")
        print(f"Saved slide {slide_num}: {output_path}")
        return output_path

    # ── MAIN SLIDE (slide 1) — full text layout ───────────────────────────────
    max_tw    = W - pad_x * 2
    hl_font   = _font(72, "ExtraBold")
    tag_font  = _font(34, "Bold")
    sub_font  = _font(36, "Regular")
    hf        = _font(38, "Bold")

    # ── TAG BADGE ─────────────────────────────────────────────────────────────
    tag_bg, tag_fg = TAG_COLOURS.get(tag, TAG_COLOURS["NEWS"])
    tag_text  = tag
    tag_pad_x, tag_pad_y = 18, 10
    tag_tw    = _tw(draw, tag_text, tag_font)
    tag_th    = _th(draw, tag_text, tag_font)
    tag_box_w = tag_tw + tag_pad_x * 2
    tag_box_h = tag_th + tag_pad_y * 2

    # ── PRE-MEASURE HEADLINE ──────────────────────────────────────────────────
    tokens   = _parse(headline)
    space_w  = _tw(draw, " ", hl_font)
    hl_lines: list[list[tuple[str, bool]]] = [[]]
    lw = 0
    for text, green in tokens:
        if re.match(r'^\s+$', text):
            continue
        ww = _tw(draw, text, hl_font)
        if lw == 0:
            hl_lines[-1].append((text, green))
            lw = ww
        elif lw + space_w + ww <= max_tw:
            hl_lines[-1].append((text, green))
            lw += space_w + ww
        else:
            hl_lines.append([(text, green)])
            lw = ww

    hl_line_h  = max((_th(draw, w, hl_font) for line in hl_lines for w, _ in line), default=72)
    hl_block_h = len(hl_lines) * (hl_line_h + 6)

    # ── PRE-MEASURE SUB-LINE ──────────────────────────────────────────────────
    sub_lines: list[str] = []
    if caption:
        sub_text = caption.split('.')[0].split('#')[0].strip()
        if len(sub_text) > 100:
            sub_text = sub_text[:98].rsplit(' ', 1)[0] + '…'
        words, cur_line, lw2 = sub_text.split(), [], 0
        sw = _tw(draw, " ", sub_font)
        for word in words:
            ww = _tw(draw, word, sub_font)
            if lw2 == 0:
                cur_line.append(word)
                lw2 = ww
            elif lw2 + sw + ww <= max_tw:
                cur_line.append(word)
                lw2 += sw + ww
            else:
                sub_lines.append(" ".join(cur_line))
                cur_line, lw2 = [word], ww
        if cur_line:
            sub_lines.append(" ".join(cur_line))
    sub_h = sum(_th(draw, ln, sub_font) + 6 for ln in sub_lines) if sub_lines else 0

    handle_h = _th(draw, HANDLE, hf)

    # ── LAYOUT: stack from bottom upward ──────────────────────────────────────
    gap1, gap2, gap3 = 28, 12, 10
    handle_y    = H - strip_h - 55 - handle_h
    sub_start_y = handle_y - gap3 - sub_h
    hl_start_y  = sub_start_y - gap2 - hl_block_h
    tag_y       = hl_start_y - gap1 - tag_box_h

    # ── DRAW TAG BADGE ────────────────────────────────────────────────────────
    draw.rounded_rectangle(
        [(pad_x, tag_y), (pad_x + tag_box_w, tag_y + tag_box_h)],
        radius=6,
        fill=tag_bg,
    )
    bb = draw.textbbox((0, 0), tag_text, font=tag_font)
    draw.text(
        (pad_x + tag_pad_x - bb[0], tag_y + tag_pad_y - bb[1]),
        tag_text, font=tag_font, fill=tag_fg,
    )

    # ── DRAW HEADLINE ─────────────────────────────────────────────────────────
    cur_y = hl_start_y
    for line in hl_lines:
        cur_x = pad_x
        for word, green in line:
            col = ACID_GREEN if green else WHITE
            draw.text((cur_x, cur_y), word, font=hl_font, fill=col)
            cur_x += _tw(draw, word, hl_font) + space_w
        cur_y += hl_line_h + 6

    # ── DRAW SUB-LINE ──────────────────────────────────────────────────────────
    cur_y = sub_start_y
    for ln in sub_lines:
        draw.text((pad_x, cur_y), ln, font=sub_font, fill=(220, 220, 220, 255))
        cur_y += _th(draw, ln, sub_font) + 6

    # ── HANDLE ────────────────────────────────────────────────────────────────
    draw.text((pad_x, handle_y), HANDLE, font=hf, fill=ACID_GREEN)

    # ── ACID GREEN BOTTOM STRIP ────────────────────────────────────────────────
    draw.rectangle([(0, H - strip_h), (W, H)], fill=ACID_GREEN)

    # ── SAVE ──────────────────────────────────────────────────────────────────
    result = canvas.convert("RGB")
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUT_DIR / f"post_{ts}.png")
    result.save(output_path, "PNG")
    kb = os.path.getsize(output_path) // 1024
    print(f"Saved: {output_path} ({kb}KB) {W}x{H}")

    if caption:
        import sys as _sys
        _enc = _sys.stdout.encoding or "utf-8"
        print("\n--- INSTAGRAM CAPTION ---")
        print(caption.encode(_enc, errors="replace").decode(_enc))
        print("-------------------------\n")

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--headline", "-H", required=True)
    p.add_argument("--caption",  "-c", default="")
    p.add_argument("--image",    "-i", default=None)
    p.add_argument("--tag",      "-t", default="NEWS",
                   choices=["NEWS", "SPOTTED", "LEAKED", "DROPPED", "BREAKING"])
    p.add_argument("--size",     "-s", default="portrait", choices=["portrait", "square"])
    p.add_argument("--focal",    "-f", default="center",   choices=["center", "top", "bottom"])
    p.add_argument("--fit",      action="store_true")
    p.add_argument("--output",   "-o", default=None)
    p.add_argument("--slide",    type=int, default=1)
    args = p.parse_args()

    create_post(
        headline=args.headline,
        caption=args.caption,
        image_path=args.image,
        tag=args.tag,
        size=args.size,
        output_path=args.output,
        focal_point=args.focal,
        fit=args.fit,
        slide_num=args.slide,
    )


if __name__ == "__main__":
    main()
