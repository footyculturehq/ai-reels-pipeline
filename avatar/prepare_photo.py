"""
Prepare the avatar source photo for each reel:
  1. Pick a random jersey photo from avatar/photos/ (AI-generated, jersey already on)
  2. Remove background with rembg
  3. Composite onto a random dark-moody room background from avatar/backgrounds/
  4. Save as a temp file and return its path

Requires: pip install rembg[gpu] pillow numpy
"""

import io
import random
from pathlib import Path

from PIL import Image

SCRIPT_DIR      = Path(__file__).parent
PHOTOS_DIR      = SCRIPT_DIR / "photos"
BACKGROUNDS_DIR = SCRIPT_DIR / "backgrounds"
FALLBACK_PHOTO  = SCRIPT_DIR / "photo_cropped.jpg"
PREPARED_PATH   = SCRIPT_DIR / "output" / "prepared_photo.png"


def _pick_photo() -> Path:
    """Pick a random jersey photo, or fall back to the default."""
    if PHOTOS_DIR.exists():
        photos = [p for p in PHOTOS_DIR.iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if photos:
            chosen = random.choice(photos)
            print(f"  Jersey photo: {chosen.name}")
            return chosen
    print(f"  No photos in avatar/photos/ — using default photo")
    return FALLBACK_PHOTO


def _pick_background() -> Path | None:
    """Pick a random room background."""
    if BACKGROUNDS_DIR.exists():
        bgs = [p for p in BACKGROUNDS_DIR.iterdir()
               if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if bgs:
            chosen = random.choice(bgs)
            print(f"  Background: {chosen.name}")
            return chosen
    return None


def _remove_background(photo_path: Path) -> Image.Image:
    """Remove background using rembg with birefnet-portrait (best for portraits)."""
    from rembg import remove, new_session
    session = new_session("birefnet-portrait")
    with open(photo_path, "rb") as f:
        data = f.read()
    result = remove(data, session=session)
    return Image.open(io.BytesIO(result)).convert("RGBA")


def _composite(person_rgba: Image.Image, bg_path: Path,
               target_size: tuple = (512, 512)) -> Image.Image:
    """Paste the person (no background) onto a room background."""
    bg = Image.open(bg_path).convert("RGB")

    # Center-crop background to square then resize
    bw, bh = bg.size
    min_dim = min(bw, bh)
    left = (bw - min_dim) // 2
    top  = (bh - min_dim) // 2
    bg = bg.crop((left, top, left + min_dim, top + min_dim))
    bg = bg.resize(target_size, Image.LANCZOS)

    # Resize person to 92% of frame, anchored bottom-center
    pw, ph = person_rgba.size
    scale = min(target_size[0] / pw, target_size[1] / ph) * 0.92
    new_w = int(pw * scale)
    new_h = int(ph * scale)
    person_rgba = person_rgba.resize((new_w, new_h), Image.LANCZOS)

    x = (target_size[0] - new_w) // 2
    y = target_size[1] - new_h   # anchor to bottom

    canvas = bg.convert("RGBA")
    canvas.paste(person_rgba, (x, y), person_rgba)
    return canvas.convert("RGB")


def prepare(target_size: tuple = (512, 512)) -> str:
    """
    Full pipeline: pick jersey photo -> remove bg -> composite on room -> save.
    Returns absolute path to the prepared PNG.
    """
    PREPARED_PATH.parent.mkdir(parents=True, exist_ok=True)

    photo_path = _pick_photo()

    print(f"  Removing background...")
    person = _remove_background(photo_path)

    bg_path = _pick_background()
    if bg_path:
        print(f"  Compositing on room background...")
        result = _composite(person, bg_path, target_size)
    else:
        print(f"  No backgrounds found — using white background")
        result = Image.new("RGB", target_size, (255, 255, 255))
        result.paste(person, (0, 0), person)

    result.save(str(PREPARED_PATH))
    size_kb = PREPARED_PATH.stat().st_size // 1024
    print(f"  Prepared photo saved: {PREPARED_PATH} ({size_kb} KB)")
    return str(PREPARED_PATH)


if __name__ == "__main__":
    path = prepare()
    print(f"Output: {path}")
