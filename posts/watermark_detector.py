"""
watermark_detector.py — Rotation-aware watermark detection for Footy Culture pipeline.

Uses Tesseract OCR (when available) at multiple angles to catch:
  • Diagonal/tiled watermarks (e.g. FOOTYHEADLINES baked diagonally across kit renders)
  • Corner URL stamps (top-right "www.footyheadlines.com" text)
  • Body-centre text overlays

Falls back to structural heuristics (brightness/variance analysis) when Tesseract
is not installed — no hard runtime dependency.

Severity levels:
  "none"            → no watermark found — image is clean
  "corner_only"     → watermark text only in outer 20% edges — renderer can trim/blur it
  "body"            → watermark in the central body zone — unusable
  "product_overlap" → diagonal/tiled pattern, or 3+ matches — unusable

Usage:
    from watermark_detector import detect_watermarks

    result = detect_watermarks(pil_image)
    # {"found": bool, "severity": str, "matches": list}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageEnhance

# ---------------------------------------------------------------------------
# Known competitor watermark strings (lowercase, no spaces)
# ---------------------------------------------------------------------------

KNOWN_WATERMARKS = [
    "footyheadlines",
    "footyheadline",
    "soccerbible",
    "caughtoffside",
    "footyissues",
    "sneakerjagers",
    "footypro",
    "thekitman",
]

# ---------------------------------------------------------------------------
# Tesseract path resolution
# ---------------------------------------------------------------------------

_TESS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]

def _find_tesseract() -> str | None:
    for p in _TESS_PATHS:
        if os.path.exists(p):
            return p
    # Try PATH
    import shutil
    return shutil.which("tesseract")


def _ocr_available() -> bool:
    return _find_tesseract() is not None


# ---------------------------------------------------------------------------
# Body-zone helper
# ---------------------------------------------------------------------------

def _is_in_body(bbox: tuple, image_size: tuple) -> bool:
    """Return True if the bbox centre is in the central 70% of the image."""
    w, h = image_size
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return (w * 0.15 < cx < w * 0.85) and (h * 0.15 < cy < h * 0.85)


# ---------------------------------------------------------------------------
# OCR-based detector
# ---------------------------------------------------------------------------

def _detect_with_ocr(img: Image.Image) -> dict:
    """
    Run Tesseract at multiple rotation angles and check for known watermark strings.
    Returns a dict with keys: found, severity, matches.
    """
    try:
        import pytesseract
        tess_path = _find_tesseract()
        if tess_path:
            pytesseract.pytesseract.tesseract_cmd = tess_path
    except ImportError:
        return _detect_structural(img)

    w, h = img.size
    matches: list[dict] = []

    # Preprocess: grayscale + contrast boost → text stands out more
    def _prep(im: Image.Image) -> Image.Image:
        im = im.convert("L")
        return ImageEnhance.Contrast(im).enhance(2.5)

    # Scan at 0° plus diagnostic angles for diagonal stamps
    for angle in [0, -30, -45, 30, 45, -15, 15]:
        if angle == 0:
            rotated = img
        else:
            rotated = img.rotate(angle, expand=True, fillcolor=(255, 255, 255))

        proc = _prep(rotated)
        try:
            data = pytesseract.image_to_data(
                proc,
                output_type=pytesseract.Output.DICT,
                config="--psm 11 --oem 3",
            )
        except Exception:
            continue

        for i, text in enumerate(data["text"]):
            # Strip ALL non-alpha characters (catches "!.FOOTYHES", "WWW.SITE.COM" etc.)
            import re as _re
            text_clean = _re.sub(r"[^a-z]", "", text.lower())
            if len(text_clean) < 4:
                continue

            for wm in KNOWN_WATERMARKS:
                wm_clean = _re.sub(r"[^a-z]", "", wm.lower())
                # Match if:
                # 1. wm string fully contained in detected text
                # 2. detected text fully contained in wm string
                # 3. detected text is a 6-char+ prefix of the wm string (OCR truncation)
                prefix_len = min(len(text_clean), max(6, len(wm_clean) // 2))
                prefix_match = (len(text_clean) >= 6 and
                                wm_clean.startswith(text_clean[:prefix_len]))
                if wm_clean in text_clean or text_clean in wm_clean or prefix_match:
                    # Translate bounding box back to original image space
                    # (for angle=0 this is a no-op; for rotated we use the
                    # rotated-image coords — good enough for body/corner classification)
                    bx = data["left"][i]
                    by = data["top"][i]
                    bw_px = data["width"][i]
                    bh_px = data["height"][i]

                    # For rotated images use rotated dimensions
                    ri_w, ri_h = rotated.size
                    cx_n = (bx + bw_px / 2) / ri_w   # normalised 0-1
                    cy_n = (by + bh_px / 2) / ri_h

                    matches.append({
                        "text": text,
                        "angle": angle,
                        "conf": data["conf"][i],
                        "cx_norm": round(cx_n, 3),
                        "cy_norm": round(cy_n, 3),
                        "bbox": (bx, by, bx + bw_px, by + bh_px),
                        "in_body": (0.15 < cx_n < 0.85) and (0.15 < cy_n < 0.85),
                    })
                    break   # don't double-count same word vs multiple watermarks

    if not matches:
        return {"found": False, "severity": "none", "matches": []}

    # Classify severity
    diagonal_match = any(abs(m["angle"]) >= 15 for m in matches)
    tiled           = len(matches) >= 3
    body_match      = any(m["in_body"] for m in matches)

    if diagonal_match or tiled or body_match:
        severity = "product_overlap"
    else:
        severity = "corner_only"   # text only at edge → renderer can trim

    return {"found": True, "severity": severity, "matches": matches}


# ---------------------------------------------------------------------------
# Structural fallback (no OCR)
# ---------------------------------------------------------------------------

def _detect_structural(img: Image.Image) -> dict:
    """
    Heuristic detector: brightness + variance analysis on image strips.
    Used when Tesseract is unavailable.

    Returns the same dict shape as _detect_with_ocr.
    """
    import statistics

    try:
        rgb = img.convert("RGB")
        w, h = rgb.size

        strip_h = max(1, int(h * 0.06))
        mid_h   = h // 2

        def _score(region: Image.Image) -> tuple[float, float]:
            px_iter = region.getdata()
            pix = [(r + g + b) / 3 for r, g, b in px_iter]
            if not pix:
                return 0.0, 0.0
            avg = sum(pix) / len(pix)
            var = sum((p - avg) ** 2 for p in pix) / len(pix)
            return avg, var

        # Pattern A: top-left URL strip
        avg_l, var_l = _score(rgb.crop((0, 0, int(w * 0.6), strip_h)))
        if 80 < avg_l < 215 and var_l > 900:
            return {"found": True, "severity": "corner_only",
                    "matches": [{"text": "(heuristic-top)", "angle": 0,
                                 "in_body": False}]}

        # Pattern B: centre-body diagonal tiling (high variance mid-strip)
        avg_m, var_m = _score(rgb.crop((0, mid_h - 40, w, mid_h + 40)))
        if var_m > 2500:
            return {"found": True, "severity": "product_overlap",
                    "matches": [{"text": "(heuristic-body)", "angle": 0,
                                 "in_body": True}]}

    except Exception:
        pass

    return {"found": False, "severity": "none", "matches": []}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"none": 0, "corner_only": 1, "body": 2, "product_overlap": 3}


def detect_watermarks(img: Image.Image) -> dict:
    """
    Master watermark detector.

    Always runs the structural heuristic (fast, no dependencies).
    Also runs OCR when Tesseract is available.
    Returns the worst (highest severity) result from either method.

    Returns:
        {
            "found": bool,
            "severity": "none" | "corner_only" | "body" | "product_overlap",
            "matches": list[dict],
            "method": "ocr+structural" | "structural",
        }
    """
    struct_result = _detect_structural(img)

    if _ocr_available():
        ocr_result = _detect_with_ocr(img)
        # Take worst severity
        if _SEVERITY_RANK[ocr_result["severity"]] >= _SEVERITY_RANK[struct_result["severity"]]:
            result = ocr_result
        else:
            result = struct_result
        result["method"] = "ocr+structural"
    else:
        result = struct_result
        result["method"] = "structural"

    return result


# ---------------------------------------------------------------------------
# CLI test helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) < 2:
        print("Usage: python watermark_detector.py <image_path> [<image_path> ...]")
        _sys.exit(1)

    for path in _sys.argv[1:]:
        img = Image.open(path)
        result = detect_watermarks(img)
        print(f"\n{path}  ({img.size[0]}x{img.size[1]})")
        print(f"  found:    {result['found']}")
        print(f"  severity: {result['severity']}")
        print(f"  method:   {result['method']}")
        for m in result["matches"]:
            print(f"  match: {m}")
