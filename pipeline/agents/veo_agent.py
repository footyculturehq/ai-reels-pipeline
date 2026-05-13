"""Pexels Agent: download free stock video clips for pexels_search storyboard segments."""

from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
PUBLIC_DIR = os.path.join(PROJECT_DIR, "public")
CLIPS_DIR = os.path.join(PUBLIC_DIR, "broll", "clips")
PEXELS_API = "https://api.pexels.com/videos/search"


def _load_api_key() -> str:
    key = os.environ.get("PEXELS_API_KEY", "")
    if not key:
        env_path = os.path.join(PROJECT_DIR, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("PEXELS_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    return key


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:40]


def _search_pexels(query: str, api_key: str, min_duration: int = 5) -> dict | None:
    """Search Pexels for a video. Returns the best matching video dict or None."""
    params = urllib.parse.urlencode({
        "query": query,
        "per_page": 10,
        "orientation": "portrait",
        "size": "medium",
    })
    url = f"{PEXELS_API}?{params}"
    req = urllib.request.Request(url, headers={
        "Authorization": api_key,
        "User-Agent": "ReelPipeline/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"    Pexels search failed for '{query}': {e}")
        return None

    videos = data.get("videos", [])
    if not videos:
        return None

    # Prefer portrait (9:16) or square clips that are long enough
    for vid in videos:
        if vid.get("duration", 0) >= min_duration:
            return vid

    return videos[0] if videos else None


def _best_download_url(video: dict) -> str | None:
    """Pick the best quality video file URL (HD preferred, SD fallback)."""
    files = video.get("video_files", [])
    # Sort: prefer HD portrait files
    portrait = [f for f in files if f.get("width", 0) < f.get("height", 0)]
    hd = [f for f in portrait if f.get("quality") in ("hd", "sd")]
    candidates = hd or portrait or files

    # Sort by resolution (biggest first)
    candidates.sort(key=lambda f: f.get("width", 0) * f.get("height", 0), reverse=True)
    return candidates[0]["link"] if candidates else None


def _download_clip(url: str, output_path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ReelPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.read())
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"    Downloaded: {os.path.basename(output_path)} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"    Download failed: {e}")
        return False


def fetch_pexels_clips(storyboard: dict) -> dict:
    api_key = _load_api_key()
    if not api_key or api_key == "your_pexels_api_key_here":
        print("Error: PEXELS_API_KEY not set in .env")
        print("Get a free key at: https://www.pexels.com/api/")
        sys.exit(1)

    segments = storyboard.get("segments", [])
    pexels_segs = [s for s in segments if s.get("type") == "pexels_search"]

    if not pexels_segs:
        print("  No pexels_search segments found.")
        return {"downloaded": 0, "failed": 0}

    print(f"  Found {len(pexels_segs)} pexels_search segments")
    os.makedirs(CLIPS_DIR, exist_ok=True)

    downloaded, failed = 0, 0
    for seg in pexels_segs:
        query = seg.get("search_query", seg.get("label", ""))
        if not query:
            failed += 1
            continue

        slug = _slugify(query)
        clip_name = f"pexels-{slug}.mp4"
        clip_path = os.path.join(CLIPS_DIR, clip_name)

        if os.path.exists(clip_path):
            print(f"  Using cached: {clip_name}")
            seg["type"] = "video"
            seg["asset_path"] = f"clips/{clip_name}"
            downloaded += 1
            continue

        print(f"  Searching Pexels: '{query}'")
        video = _search_pexels(query, api_key)

        # Fallback: try first keyword only
        if not video and " " in query:
            fallback = query.split()[0]
            print(f"    Retrying with: '{fallback}'")
            video = _search_pexels(fallback, api_key)

        if not video:
            print(f"    No results for '{query}'")
            failed += 1
            continue

        url = _best_download_url(video)
        if not url:
            failed += 1
            continue

        if _download_clip(url, clip_path):
            seg["type"] = "video"
            seg["asset_path"] = f"clips/{clip_name}"
            downloaded += 1
        else:
            failed += 1

        # Pexels rate limit: be polite
        time.sleep(0.5)

    return {"downloaded": downloaded, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="Pexels Agent (replaces Veo)")
    parser.add_argument("--reel-id", required=True)
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    if not state.exists():
        print(f"Error: No pipeline state for {args.reel_id}")
        sys.exit(1)

    storyboard = state.get_output("storyboard")
    if not storyboard:
        print("Error: No storyboard found. Run storyboard agent first.")
        sys.exit(1)

    result = fetch_pexels_clips(storyboard)

    storyboard_path = os.path.join(state.reel_dir, "storyboard.json")
    with open(storyboard_path, "w") as f:
        json.dump(storyboard, f, indent=2)

    print(f"  Downloaded: {result['downloaded']}, Failed: {result['failed']}")
    state.complete_stage("veo", "storyboard.json", result)


if __name__ == "__main__":
    main()
