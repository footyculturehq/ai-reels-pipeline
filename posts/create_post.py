"""
Footy Culture HQ — Static Image Post Generator
Rap TV style for football boots & jerseys.

Image:
  - Full-bleed photo, top ~65%
  - Smooth gradient fade from image into pitch black
  - NEWS/SPOTTED/RUMOUR badge on image top-left
  - Large headline — numbers, brands, key terms auto acid-green
  - {curly braces} = force acid green on any word
  - @footyculturehq handle bottom-left

Caption (printed to terminal, paste into Instagram):
  - Body copy, credit, sizes, hashtags — all goes in the IG caption

Usage:
  python posts/create_post.py \
    --headline "Salah spotted in {unreleased} Nike Phantom GX2" \
    --caption "Training ground leak — not on the website yet. Sizes dropped in the link in bio. Pic: @bootroom_x" \
    --image path/to/boot.jpg \
    --tag "SPOTTED"
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

ACID_GREEN  = (176, 255, 0)
PITCH_BLACK = (0, 0, 0)
WHITE       = (255, 255, 255)
HANDLE      = "@footyculturehq"

SIZES = {"portrait": (1080, 1440), "square": (1080, 1080)}

# Words that are auto-highlighted in acid green (case-insensitive)
AUTO_GREEN = {
    # brands
    "nike","adidas","puma","mizuno","new balance","nb","umbro","copa",
    "predator","mercurial","phantom","tiempo","superfly","vapor",
    "future","king","tekela","furon","morelia","actura",
    # actions / hype
    "exclusive","unreleased","leaked","limited","sold out","sold","out",
    "dropped","dropping","spotted","confirmed","official","cancelled",
    # money
    "profit","flip","resell","resale","retail",
    # clubs / competitions
    "premier league","champions league","world cup","euro",
}

IMAGE_RATIO  = 0.65   # image takes top 65%
FADE_START   = 0.15   # fade begins at 15% of image height from top
FADE_POWER   = 0.85   # <1 = concave: hits hard early, ideal for white-bg product shots
TOP_VIGNETTE = 130    # px — black-to-transparent gradient at top (kills watermarks)
TOP_SOLID    = 35     # px of pure black at the very top (guaranteed watermark kill)


def _draw_boot_icon(draw, x, y, width=130, color=ACID_GREEN, lw=5):
    """
    Draw an iconic football boot outline (right-facing).
    Key: collar on the left rises sharply ABOVE the flat vamp — that's
    the visual cue that reads immediately as a football boot.
    """
    s = width / 100.0

    # Outer profile — simplified & angular so it reads at small sizes
    pts = [
        (x + int(0*s),  y + int(38*s)),  # heel base
        (x + int(0*s),  y + int(8*s)),   # collar back rises vertically
        (x + int(13*s), y + int(0*s)),   # collar PEAK  ← topmost point
        (x + int(32*s), y + int(18*s)),  # steep drop from collar to vamp
        (x + int(62*s), y + int(20*s)),  # flat vamp (much lower than collar)
        (x + int(82*s), y + int(22*s)),  # toe shoulder
        (x + int(100*s),y + int(40*s)),  # toe tip (furthest right)
        (x + int(92*s), y + int(60*s)),  # toe underside
        (x + int(72*s), y + int(66*s)),  # forefoot sole
        (x + int(8*s),  y + int(66*s)),  # sole — straight flat line
        (x + int(0*s),  y + int(58*s)),  # heel sole corner
        (x + int(0*s),  y + int(38*s)),  # close
    ]
    draw.line(pts, fill=color, width=lw)

    # Studs — 3 solid filled circles under sole
    sole_y = y + int(66*s)
    for sx_norm in [18, 42, 65]:
        cx = x + int(sx_norm * s)
        r  = max(4, int(5 * s))
        draw.ellipse([(cx - r, sole_y + 2), (cx + r, sole_y + 2 + r * 2)], fill=color)


def _font(size: int, weight: str = "ExtraBold"):
    for p in [
        str(FONT_DIR / f"Inter-{weight}.ttf"),
        str(FONT_DIR / "Inter-Bold.ttf"),
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _tw(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def _th(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def _is_auto_green(word: str) -> bool:
    w = word.lower().strip(".,!?:;'\"")
    if re.match(r'^\d+(?:[.,]\d+)?[%£$€]?$', w):
        return True
    if w in AUTO_GREEN:
        return True
    return False


def _parse(headline: str) -> list[tuple[str, bool]]:
    """Split headline into (token, is_green) pairs, preserving spaces."""
    tokens = re.split(r'(\{[^}]+\})', headline)
    result = []
    for tok in tokens:
        if tok.startswith('{') and tok.endswith('}'):
            result.append((tok[1:-1], True))
        else:
            # split on spaces keeping them
            parts = re.split(r'(\s+)', tok)
            for part in parts:
                if not part:
                    continue
                if re.match(r'^\s+$', part):
                    result.append((part, False))   # whitespace token
                else:
                    result.append((part, _is_auto_green(part)))
    return result


def _draw_headline(draw, tokens, font, x, y, max_w, line_gap=10):
    """Word-wrap and draw multi-colour headline. Returns y after last line."""
    space_w = _tw(draw, " ", font)

    # Build wrapped lines
    lines = [[]]
    line_w = 0
    for text, green in tokens:
        if re.match(r'^\s+$', text):
            continue   # skip whitespace tokens — we re-add spaces between words
        ww = _tw(draw, text, font)
        if line_w == 0:
            lines[-1].append((text, green))
            line_w = ww
        elif line_w + space_w + ww <= max_w:
            lines[-1].append((text, green))
            line_w += space_w + ww
        else:
            lines.append([(text, green)])
            line_w = ww

    cur_y = y
    for line in lines:
        cur_x = x
        lh = 0
        for word, green in line:
            col = ACID_GREEN if green else WHITE
            draw.text((cur_x, cur_y), word, font=font, fill=col)
            lh = max(lh, _th(draw, word, font))
            cur_x += _tw(draw, word, font) + space_w
        cur_y += lh + line_gap

    return cur_y


def create_post(
    headline: str,
    caption: str = "",
    image_path: str = None,
    tag: str = "NEWS",
    size: str = "portrait",
    output_path: str = None,
    focal_point: str = "center",
    fit: bool = False,
) -> str:
    W, H = SIZES.get(size, SIZES["portrait"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    img_h = int(H * IMAGE_RATIO)
    canvas = Image.new("RGB", (W, H), PITCH_BLACK)
    draw   = ImageDraw.Draw(canvas)

    # ── PHOTO ──────────────────────────────────────────────────────────────
    # fit=True  → letterbox: entire image visible, black bars fill any gaps
    # fit=False → cover/crop: fills the zone, anchored by focal_point
    img_paste_y = 0   # track where image top lands on canvas (for vignette)
    if image_path and os.path.exists(image_path):
        img = Image.open(image_path).convert("RGB")
        if fit:
            # Scale so WHOLE image fits inside W × img_h, centred on black
            scale = min(W / img.width, img_h / img.height)
            nw    = int(img.width  * scale)
            nh    = int(img.height * scale)
            img   = img.resize((nw, nh), Image.LANCZOS)
            ox    = (W    - nw) // 2
            oy    = (img_h - nh) // 2
            img_paste_y = oy   # image starts below any letterbox padding
            canvas.paste(img, (ox, oy))
        else:
            ir, zr = img.width / img.height, W / img_h
            if ir > zr:
                nh, nw = img_h, int(img_h * ir)
            else:
                nw, nh = W, int(W / ir)
            img = img.resize((nw, nh), Image.LANCZOS)
            ox = (nw - W) // 2
            focal = (focal_point or "center").lower()
            if focal == "top":
                oy = 0
            elif focal == "bottom":
                oy = nh - img_h
            else:
                oy = (nh - img_h) // 2
            img = img.crop((ox, oy, ox + W, oy + img_h))
            canvas.paste(img, (0, 0))
    else:
        draw.rectangle([(0, 0), (W, img_h)], fill=(18, 18, 18))

    # ── GRADIENT FADE (image → black) ──────────────────────────────────────
    # Starts partway into the image, reaches fully black at img_h
    fade_start_px = int(img_h * FADE_START)
    fade_h        = img_h - fade_start_px
    overlay = Image.new("RGBA", (W, img_h), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for row in range(fade_h):
        t     = row / fade_h                        # 0 → 1
        alpha = int(255 * (t ** FADE_POWER))        # slow start, fast finish
        ov_draw.rectangle(
            [(0, fade_start_px + row), (W, fade_start_px + row + 1)],
            fill=(0, 0, 0, alpha)
        )
    canvas.paste(Image.alpha_composite(
        Image.new("RGBA", (W, img_h), (0, 0, 0, 0)),
        overlay
    ).convert("RGB"), (0, 0), mask=overlay.split()[3])

    # ── TOP VIGNETTE — kills watermarks wherever the image starts ──────────
    # Solid black for TOP_SOLID px, then tapers to transparent over remaining rows
    top_ov = Image.new("RGBA", (W, TOP_VIGNETTE), (0, 0, 0, 0))
    tv_draw = ImageDraw.Draw(top_ov)
    taper_h = TOP_VIGNETTE - TOP_SOLID
    for row in range(TOP_VIGNETTE):
        if row < TOP_SOLID:
            alpha = 255                               # pure black — kills any watermark
        else:
            t     = 1.0 - ((row - TOP_SOLID) / taper_h)
            alpha = int(255 * (t ** 0.45))            # fast taper to transparent
        tv_draw.rectangle([(0, row), (W, row + 1)], fill=(0, 0, 0, alpha))
    canvas.paste(
        Image.alpha_composite(Image.new("RGBA", (W, TOP_VIGNETTE), (0,0,0,0)), top_ov).convert("RGB"),
        (0, img_paste_y),
        mask=top_ov.split()[3]
    )

    # ── BOOT ICON on image (top-left) ─────────────────────────────────────────
    _draw_boot_icon(draw, x=42, y=38, width=96, color=ACID_GREEN, lw=5)

    # ── LAYOUT: anchor ALL text to the bottom, stack upward ────────────────
    pad_x    = 48
    max_tw   = W - pad_x * 2
    strip_h  = 7

    hl_font  = _font(70, "ExtraBold")
    sub_font = _font(36, "Regular")
    hf       = _font(38, "ExtraBold")
    fn_font  = _font(32, "ExtraBold")

    # ── Pre-measure FOOTY NEWS label ───────────────────────────────────────
    fn_text    = "FOOTY NEWS"
    fn_bb      = draw.textbbox((0, 0), fn_text, font=fn_font)
    fn_tw      = fn_bb[2] - fn_bb[0]
    fn_th      = fn_bb[3] - fn_bb[1]   # true visual height
    fn_top_off = fn_bb[1]               # gap between draw-y and visual top
    fn_pad_x, fn_pad_y = 16, 13
    fn_box_h   = fn_th + fn_pad_y * 2  # box height based on visual height

    # ── Pre-measure sub-info lines ─────────────────────────────────────────
    sub_lines = []
    if caption:
        sub_text = caption.split('.')[0].split('#')[0].strip()
        if len(sub_text) > 110:
            sub_text = sub_text[:108].rsplit(' ', 1)[0] + '...'
        words = sub_text.split()
        cur_line, lw = [], 0
        sw = _tw(draw, " ", sub_font)
        for word in words:
            ww = _tw(draw, word, sub_font)
            if lw == 0:
                cur_line.append(word)
                lw = ww
            elif lw + sw + ww <= max_tw:
                cur_line.append(word)
                lw += sw + ww
            else:
                sub_lines.append(" ".join(cur_line))
                cur_line, lw = [word], ww
        if cur_line:
            sub_lines.append(" ".join(cur_line))

    sub_block_h = sum(_th(draw, ln, sub_font) + 6 for ln in sub_lines) if sub_lines else 0

    # ── Pre-measure headline lines ─────────────────────────────────────────
    tokens = _parse(headline)
    space_w = _tw(draw, " ", hl_font)
    hl_lines = [[]]
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

    hl_line_h   = max((_th(draw, w, hl_font) for line in hl_lines for w, _ in line), default=70)
    hl_block_h  = len(hl_lines) * (hl_line_h + 8)

    handle_line_h = _th(draw, HANDLE, hf)

    # ── Position everything from the bottom, stacked tight ─────────────────
    gap_fn_hl    = 30   # between FOOTY NEWS box and headline
    gap_hl_sub   = 12   # between headline and sub-info
    gap_sub_hdl  = 10   # between sub-info and handle

    handle_y    = H - strip_h - 60 - handle_line_h
    sub_start_y = handle_y - gap_sub_hdl - sub_block_h
    hl_start_y  = sub_start_y - gap_hl_sub - hl_block_h
    fn_y        = hl_start_y - gap_fn_hl - fn_box_h

    # Clamp: if FOOTY NEWS would overlap the image zone, push the ENTIRE
    # text block down so FOOTY NEWS sits just below the image, not above.
    fn_y_min = img_h + 28
    if fn_y < fn_y_min:
        fn_y        = fn_y_min
        hl_start_y  = fn_y + fn_box_h + gap_fn_hl
        sub_start_y = hl_start_y + hl_block_h + gap_hl_sub
        handle_y    = sub_start_y + sub_block_h + gap_sub_hdl

    fn_x = pad_x

    # ── FOOTY NEWS label — white stencil box ──────────────────────────────
    draw.rectangle(
        [(fn_x, fn_y), (fn_x + fn_tw + fn_pad_x * 2, fn_y + fn_box_h)],
        fill=WHITE
    )
    # Compensate for font's internal top offset so visual padding is equal top+bottom
    draw.text(
        (fn_x + fn_pad_x - fn_bb[0], fn_y + fn_pad_y - fn_top_off),
        fn_text, font=fn_font, fill=PITCH_BLACK
    )

    # ── DRAW HEADLINE ───────────────────────────────────────────────────────
    cur_y = hl_start_y
    for line in hl_lines:
        cur_x = pad_x
        for word, green in line:
            col = ACID_GREEN if green else WHITE
            draw.text((cur_x, cur_y), word, font=hl_font, fill=col)
            cur_x += _tw(draw, word, hl_font) + space_w
        cur_y += hl_line_h + 8

    # ── DRAW SUB-INFO ───────────────────────────────────────────────────────
    cur_y = sub_start_y
    for ln in sub_lines:
        draw.text((pad_x, cur_y), ln, font=sub_font, fill=(200, 200, 200))
        cur_y += _th(draw, ln, sub_font) + 6

    # ── HANDLE bottom-left ─────────────────────────────────────────────────
    draw.text((pad_x, handle_y), HANDLE, font=hf, fill=ACID_GREEN)

    # ── Acid green bottom strip ─────────────────────────────────────────────
    draw.rectangle([(0, H - strip_h), (W, H)], fill=ACID_GREEN)

    # ── Save ───────────────────────────────────────────────────────────────
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(OUT_DIR / f"post_{ts}.png")

    canvas.save(output_path, "PNG")
    kb = os.path.getsize(output_path) // 1024
    print(f"Saved: {output_path} ({kb}KB) {W}x{H}")

    # ── Print IG caption to terminal ────────────────────────────────────────
    if caption:
        import sys as _sys
        _enc = _sys.stdout.encoding or "utf-8"
        _safe = caption.encode(_enc, errors="replace").decode(_enc)
        print("\n--- INSTAGRAM CAPTION ---")
        print(_safe)
        print("-------------------------\n")

    return output_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--headline", "-H", required=True,
                   help="Headline. Use {word} to force acid green on any word.")
    p.add_argument("--caption", "-c", default="",
                   help="Instagram caption text (sizes, credit, hashtags) — printed to terminal, not on image.")
    p.add_argument("--image",   "-i", default=None)
    p.add_argument("--tag",     "-t", default="NEWS",
                   choices=["NEWS","SPOTTED","RUMOUR","DROPPED","EXCLUSIVE","BREAKING"])
    p.add_argument("--size",    "-s", default="portrait", choices=["portrait","square"])
    p.add_argument("--focal",   "-f", default="center", choices=["center","top","bottom"],
                   help="Crop anchor for player images: top=show face, bottom=show feet")
    p.add_argument("--fit", action="store_true",
                   help="Letterbox the image so the WHOLE boot/item is always in frame (no cropping)")
    p.add_argument("--output",  "-o", default=None)
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
    )

if __name__ == "__main__":
    main()
