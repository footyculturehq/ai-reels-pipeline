"""Image Resolver Agent: download images for rapid image list segments via Wikipedia."""

from __future__ import annotations
import argparse, json, os, re, sys, urllib.parse, urllib.request

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
BROLL_DIR = os.path.join(PROJECT_DIR, "public", "broll")
WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary"


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _fetch_wiki_image(query: str) -> str | None:
    title = query.strip().replace(" ", "_")
    url = f"{WIKI_API}/{urllib.parse.quote(title, safe='')}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ReelPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("originalimage", {}).get("source")
    except Exception as e:
        print(f"    Wikipedia lookup failed for '{query}': {e}")
        return None


def _download_image(url: str, output_path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ReelPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.read())
        return True
    except Exception:
        return False


def resolve_images(storyboard: dict, reel_id: str) -> dict:
    output_dir = os.path.join(BROLL_DIR, "topics", reel_id)
    segments = storyboard.get("segments", [])
    resolved, failed = 0, 0

    for seg in segments:
        if seg.get("type") != "image_needed":
            continue
        query = seg.get("image_query", seg.get("label", ""))
        label = seg.get("label", query)
        slug = _slugify(label)
        if not query:
            failed += 1
            continue

        image_url = _fetch_wiki_image(query)
        if not image_url and " " in query:
            parts = query.split()
            simplified = f"{parts[0]} {parts[-1]}" if len(parts) > 2 else query
            image_url = _fetch_wiki_image(simplified)

        if not image_url:
            failed += 1
            continue

        ext = ".png" if ".png" in image_url.lower() else ".jpg"
        output_path = os.path.join(output_dir, f"{slug}{ext}")
        rel_path = f"topics/{reel_id}/{slug}{ext}"

        if not os.path.exists(output_path):
            if not _download_image(image_url, output_path):
                failed += 1
                continue

        seg["type"] = "screenshot"
        seg["asset_path"] = rel_path
        seg["framing"] = {"objectPosition": "center center", "scaleFrom": 1.0, "scaleTo": 1.08}
        resolved += 1

    return {"resolved": resolved, "failed": failed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reel-id", required=True)
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    storyboard = state.get_output("storyboard")
    if not storyboard:
        print("Error: No storyboard found. Run storyboard agent first.")
        sys.exit(1)

    result = resolve_images(storyboard, args.reel_id)

    storyboard_path = os.path.join(state.reel_dir, "storyboard.json")
    with open(storyboard_path, "w") as f:
        json.dump(storyboard, f, indent=2)

    print(f"  Resolved: {result['resolved']}, Failed: {result['failed']}")


if __name__ == "__main__":
    main()
