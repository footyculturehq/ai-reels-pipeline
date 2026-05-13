"""Assembly Agent: convert storyboard to ReelConfig JSON and optionally render."""

from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
PUBLIC_DIR = os.path.join(PROJECT_DIR, "public")
CONFIG_DIR = os.path.join(PUBLIC_DIR, "config")
OUT_DIR = os.path.join(PROJECT_DIR, "out")


def _seg_to_broll(seg: dict) -> dict | None:
    """Convert a storyboard segment to a BRollSegment."""
    seg_type = seg.get("type")
    framing = seg.get("framing", {})

    broll: dict = {
        "startSec": round(seg["start"], 3),
        "endSec": round(seg["end"], 3),
        "objectPosition": framing.get("objectPosition", "center center"),
        "scaleFrom": framing.get("scaleFrom", 1.0),
        "scaleTo": framing.get("scaleTo", 1.05),
    }

    if seg.get("_speech"):
        broll["_speech"] = seg["_speech"]

    asset_path = seg.get("asset_path", "")

    if seg_type == "video":
        clip_name = os.path.basename(asset_path) if asset_path else ""
        if not clip_name:
            return None
        broll["video"] = clip_name
        video_start = framing.get("videoStartSec", 0)
        if video_start:
            broll["videoStartSec"] = video_start

    elif seg_type == "screenshot":
        if not asset_path:
            return None
        # asset_path is relative to public/broll/ or public/broll/topics/
        # Remotion staticFile serves from public/, so we use the relative path under broll/
        broll["image"] = asset_path

    else:
        return None

    return broll


def _build_caption_chunks(transcript: dict) -> list[dict]:
    """Group words into 1-3 word caption chunks."""
    words = transcript.get("words", [])
    if not words:
        return []

    chunks = []
    i = 0
    while i < len(words):
        # Group 1-3 words per chunk
        group_size = 2
        if i + 2 < len(words):
            # Vary between 1-3 based on word length
            total_chars = sum(len(words[j]["word"]) for j in range(i, min(i + 3, len(words))))
            group_size = 1 if total_chars > 20 else (3 if total_chars < 12 else 2)

        group = words[i:i + group_size]
        text = " ".join(w["word"] for w in group).strip()
        if text:
            chunks.append({
                "text": text,
                "startSec": round(group[0]["start"], 3),
                "endSec": round(group[-1]["end"], 3),
            })
        i += group_size

    return chunks


def validate_config(config: dict, public_dir: str) -> list[str]:
    """Validate the assembled config. Returns list of errors."""
    errors = []

    # Check for PLACEHOLDERs
    config_str = json.dumps(config)
    if "PLACEHOLDER" in config_str:
        errors.append("Config contains PLACEHOLDER values")

    segments = config.get("brollSegments", [])
    if not segments:
        errors.append("No broll segments")

    # Check continuity
    for i in range(len(segments) - 1):
        gap = segments[i + 1]["startSec"] - segments[i]["endSec"]
        if gap > 0.1:
            errors.append(f"Gap {gap:.2f}s between segments {i} and {i+1}")

    # Check files exist
    for seg in segments:
        if "video" in seg:
            path = os.path.join(public_dir, "broll", "clips", seg["video"])
            if not os.path.exists(path):
                errors.append(f"Missing video: {seg['video']}")
        elif "image" in seg:
            path = os.path.join(public_dir, "broll", seg["image"])
            if not os.path.exists(path):
                errors.append(f"Missing image: {seg['image']}")

    # Check captions
    if not config.get("captionChunks"):
        errors.append("No caption chunks")

    return errors


def assemble(reel_id: str, storyboard: dict, transcript: dict, state_data: dict,
             crossfade_frames: int = 5, avatar_margin: int = -280) -> dict:
    segments = storyboard.get("segments", [])
    broll_segments = []

    for seg in segments:
        broll = _seg_to_broll(seg)
        if broll:
            broll_segments.append(broll)

    caption_chunks = _build_caption_chunks(transcript)

    total_duration = storyboard.get("total_duration", 30.0)
    duration_frames = round(total_duration * 25)  # 25fps

    avatar_src = state_data.get("avatar_src", "")

    config = {
        "id": reel_id,
        "duration": duration_frames,
        "avatarSrc": avatar_src,
        "avatarMarginTop": avatar_margin,
        "crossfadeFrames": crossfade_frames,
        "brollSegments": broll_segments,
        "captionChunks": caption_chunks,
        "scenes": [],
    }

    return config


def render(reel_id: str, config_path: str, out_path: str) -> bool:
    """Render the reel via Remotion CLI."""
    import tempfile as _tmp; props_path = _tmp.gettempdir().replace("\\", "/") + f"/reel-props-{reel_id}.json"

    with open(config_path) as f:
        config = json.load(f)

    with open(props_path, "w") as f:
        json.dump({"config": config}, f)

    cmd = [
        "npx.cmd", "remotion", "render", "src/Root.tsx", "DynamicReel", out_path,
        "--codec=h264", f"--props={props_path}",
    ]
    print(f"  Rendering: {out_path}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR, shell=False)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Assembly Agent")
    parser.add_argument("--reel-id", required=True)
    parser.add_argument("--render", action="store_true", help="Render after assembly")
    parser.add_argument("--crossfade", type=int, default=5)
    parser.add_argument("--avatar-margin", type=int, default=-280)
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    if not state.exists():
        print(f"Error: No pipeline state for {args.reel_id}")
        sys.exit(1)

    storyboard = state.get_output("storyboard")
    if not storyboard:
        print("Error: No storyboard found.")
        sys.exit(1)

    transcript_path = state.get_config("transcript_path", "")
    if not transcript_path or not os.path.exists(transcript_path):
        print(f"Error: transcript not found at {transcript_path}")
        sys.exit(1)

    with open(transcript_path) as f:
        transcript = json.load(f)

    state_data = {
        "avatar_src": state.get_config("avatar_src", ""),
    }

    print(f"  Assembling config for {args.reel_id}...")
    config = assemble(
        reel_id=args.reel_id,
        storyboard=storyboard,
        transcript=transcript,
        state_data=state_data,
        crossfade_frames=args.crossfade,
        avatar_margin=args.avatar_margin,
    )

    errors = validate_config(config, PUBLIC_DIR)
    if errors:
        print("  Validation errors:")
        for e in errors:
            print(f"    ERROR: {e}")
        print("  Fix errors before rendering.")
        sys.exit(1)

    os.makedirs(CONFIG_DIR, exist_ok=True)
    config_filename = f"reel-config-{args.reel_id}.json"
    config_path = os.path.join(CONFIG_DIR, config_filename)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  Config saved: {config_path}")
    print(f"  Segments: {len(config['brollSegments'])} | Captions: {len(config['captionChunks'])}")
    print(f"  Duration: {config['duration']} frames ({config['duration']/25:.1f}s)")

    rendered_path = None
    if args.render:
        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, f"{args.reel_id}.mp4")
        success = render(args.reel_id, config_path, out_path)
        if success:
            rendered_path = out_path
            print(f"  Rendered: {out_path}")
        else:
            print("  Render failed. Check Remotion output above.")

    state.complete_stage("assemble", config_filename, {
        "segments": len(config["brollSegments"]),
        "captions": len(config["captionChunks"]),
        "duration_frames": config["duration"],
        "rendered": rendered_path,
    })


if __name__ == "__main__":
    main()
