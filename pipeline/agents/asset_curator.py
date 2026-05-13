"""Asset Curator Agent: collect, scan, and grade all raw B-roll footage."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
BROLL_DIR = os.path.join(PROJECT_DIR, "public", "broll")
CLIPS_DIR = os.path.join(BROLL_DIR, "clips")
TOPICS_DIR = os.path.join(BROLL_DIR, "topics")
LOGOS_DIR = os.path.join(PROJECT_DIR, "public", "logos")

BRIGHTNESS_REJECT = 30
BRIGHTNESS_WARN = 50
QUALITY_REJECT = 40
MIN_RESOLUTION = 720
MIN_VIDEO_DURATION = 3.0

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".webm", ".mov")


def _ffprobe_info(filepath: str) -> dict:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_streams", "-show_format", filepath]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return {}


def _get_brightness(filepath: str, is_video: bool = False) -> float:
    try:
        input_args = ["-i", filepath]
        if is_video:
            input_args = ["-t", "3"] + input_args

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               *input_args, "-vf", "signalstats", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        yavg_values = []
        for line in result.stderr.split("\n"):
            if "YAVG" in line:
                parts = line.split("YAVG=")
                if len(parts) > 1:
                    try:
                        yavg_values.append(float(parts[1].split()[0]))
                    except (ValueError, IndexError):
                        pass
        if yavg_values:
            return sum(yavg_values) / len(yavg_values)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return -1


def _get_motion_score(filepath: str) -> float:
    try:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info",
               "-t", "5", "-i", filepath,
               "-vf", "select='gt(scene,0.1)',metadata=print", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        scene_changes = result.stderr.count("scene_score=")
        return min(scene_changes * 20, 100)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1


def grade_asset(filepath: str) -> dict:
    is_video = filepath.lower().endswith(VIDEO_EXTS)
    result = {"brightness": -1, "resolution": "unknown", "width": 0, "height": 0}

    if is_video:
        result["duration_sec"] = 0.0
        result["motion_score"] = -1

    probe = _ffprobe_info(filepath)
    streams = probe.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video_stream:
        w = int(video_stream.get("width", 0))
        h = int(video_stream.get("height", 0))
        result["width"] = w
        result["height"] = h
        result["resolution"] = f"{w}x{h}"

    if is_video:
        fmt = probe.get("format", {})
        duration = float(fmt.get("duration", 0))
        result["duration_sec"] = round(duration, 1)
        result["motion_score"] = _get_motion_score(filepath)

    result["brightness"] = round(_get_brightness(filepath, is_video=is_video), 1)

    score = 50
    brightness = result["brightness"]
    if brightness >= 0:
        if brightness >= 100:
            score += 30
        elif brightness >= BRIGHTNESS_WARN:
            score += 20
        elif brightness >= BRIGHTNESS_REJECT:
            score += 5
        else:
            score -= 25

    min_dim = min(result["width"], result["height"]) if result["width"] > 0 else 0
    if min_dim >= 1080:
        score += 20
    elif min_dim >= 720:
        score += 10
    elif min_dim > 0:
        score -= 10

    if is_video:
        dur = result["duration_sec"]
        if dur >= MIN_VIDEO_DURATION:
            score += 10
        elif dur > 0:
            score += 5
        motion = result.get("motion_score", -1)
        if motion >= 60:
            score += 10
        elif motion >= 30:
            score += 5

    result["quality_score"] = max(0, min(100, score))
    return result


def scan_and_grade(tool_name: str, scan_all: bool = False, extra_dirs: list = None) -> list:
    topic_key = tool_name.lower().replace(" ", "-")
    assets = []

    topic_dir = os.path.join(TOPICS_DIR, topic_key)
    if os.path.isdir(topic_dir):
        for f in sorted(os.listdir(topic_dir)):
            if f.lower().endswith(IMAGE_EXTS):
                filepath = os.path.join(topic_dir, f)
                grade = grade_asset(filepath)
                assets.append({
                    "id": os.path.splitext(f)[0], "type": "screenshot",
                    "path": f"topics/{topic_key}/{f}", "abs_path": filepath,
                    "source": "existing", **grade,
                })

    if os.path.isdir(CLIPS_DIR):
        for f in sorted(os.listdir(CLIPS_DIR)):
            if not f.lower().endswith(VIDEO_EXTS):
                continue
            if scan_all or topic_key in f.lower():
                filepath = os.path.join(CLIPS_DIR, f)
                grade = grade_asset(filepath)
                assets.append({
                    "id": os.path.splitext(f)[0], "type": "video",
                    "path": f"clips/{f}", "abs_path": filepath,
                    "source": "existing", **grade,
                })

    for extra in (extra_dirs or []):
        if not os.path.isdir(extra):
            continue
        for f in sorted(os.listdir(extra)):
            if f.lower().endswith(IMAGE_EXTS + VIDEO_EXTS):
                filepath = os.path.join(extra, f)
                grade = grade_asset(filepath)
                is_video = f.lower().endswith(VIDEO_EXTS)
                assets.append({
                    "id": os.path.splitext(f)[0],
                    "type": "video" if is_video else "screenshot",
                    "path": f"clips/{f}", "abs_path": filepath,
                    "source": "screen_recording", **grade,
                })

    return assets


def apply_quality_gates(assets: list) -> list:
    for asset in assets:
        if asset.get("type") == "logo":
            asset["approved"] = True
            asset["rejection_reason"] = ""
            continue

        reasons = []
        brightness = asset.get("brightness", -1)
        if 0 <= brightness < BRIGHTNESS_REJECT:
            reasons.append(f"Too dark (brightness {brightness:.0f}/255)")

        min_dim = min(asset.get("width", 0), asset.get("height", 0))
        if 0 < min_dim < MIN_RESOLUTION:
            reasons.append(f"Resolution too low ({asset.get('resolution', '?')})")

        if asset.get("type") == "video":
            dur = asset.get("duration_sec", 0)
            if 0 < dur < MIN_VIDEO_DURATION:
                reasons.append(f"Too short ({dur:.1f}s)")

        score = asset.get("quality_score", 0)
        if score < QUALITY_REJECT and not reasons:
            reasons.append(f"Quality score too low ({score}/100)")

        asset["approved"] = len(reasons) == 0
        asset["rejection_reason"] = "; ".join(reasons) if reasons else ""
    return assets


def build_manifest(reel_id: str, tool_name: str, assets: list) -> dict:
    clean_assets = [{k: v for k, v in a.items() if k != "abs_path"} for a in assets]
    approved = [a for a in assets if a.get("approved")]
    rejected = [a for a in assets if not a.get("approved")]
    return {
        "reel_id": reel_id, "tool_name": tool_name,
        "curated_at": datetime.now(timezone.utc).isoformat(),
        "assets": clean_assets,
        "summary": {
            "total": len(assets), "approved": len(approved), "rejected": len(rejected),
        },
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Asset Curator")
    parser.add_argument("--reel-id", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--extra-dir", action="append", default=[])
    parser.add_argument("--scan-all", action="store_true")
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    if not state.exists():
        state.init(tool_name=args.tool)

    print(f"  Curating assets for: {args.tool}")
    assets = scan_and_grade(args.tool, scan_all=args.scan_all, extra_dirs=args.extra_dir)
    if not assets:
        topic_key = args.tool.lower().replace(" ", "-")
        print(f"  No assets found. Add files to public/broll/topics/{topic_key}/")
        return

    assets = apply_quality_gates(assets)
    manifest = build_manifest(args.reel_id, args.tool, assets)

    output_path = os.path.join(state.reel_dir, "asset-manifest.json")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Total: {manifest['summary']['total']} | Approved: {manifest['summary']['approved']}")
    state.complete_stage("curate", "asset-manifest.json", manifest["summary"])


if __name__ == "__main__":
    main()
