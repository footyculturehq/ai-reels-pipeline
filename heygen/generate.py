#!/usr/bin/env python3
"""Generate a HeyGen avatar video. End-to-end: submit -> poll -> download."""

import argparse
import json
import os
import sys

from heygen_client import generate_video, wait_for_video, download_video, get_profile

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main():
    parser = argparse.ArgumentParser(description="Generate a HeyGen avatar video")
    parser.add_argument("--profile", help="Named profile from heygen_config.json")
    parser.add_argument("--avatar", help="Avatar ID (overrides profile)")
    parser.add_argument("--voice", help="Voice ID (overrides profile)")
    parser.add_argument("--script", required=True, help="Script text")
    parser.add_argument("--title", default="Reel Video", help="Video title")
    parser.add_argument("--landscape", action="store_true", help="16:9 instead of 9:16")
    parser.add_argument("--timeout", type=int, default=600, help="Max wait seconds")
    args = parser.parse_args()

    avatar_id = args.avatar
    voice_id = args.voice
    voice_speed = 1.0
    voice_emotion = None

    if args.profile:
        profile = get_profile(args.profile)
        avatar_id = avatar_id or profile["avatar_id"]
        voice_id = voice_id or profile["voice_id"]
        voice_speed = profile.get("voice_speed", 1.0)
        voice_emotion = profile.get("voice_emotion")

    if not avatar_id or not voice_id:
        print("Error: provide --profile or both --avatar and --voice")
        sys.exit(1)

    dimension = (
        {"width": 1920, "height": 1080} if args.landscape
        else {"width": 1080, "height": 1920}
    )

    print(f"\nGenerating video...")
    video_id = generate_video(
        script=args.script, avatar_id=avatar_id, voice_id=voice_id,
        title=args.title, dimension=dimension,
        voice_speed=voice_speed, voice_emotion=voice_emotion,
    )

    print(f"\nWaiting for video {video_id}...")
    result = wait_for_video(video_id, poll_interval=15, timeout=args.timeout)

    video_url = result["video_url"]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"{video_id}.mp4")
    download_video(video_url, output_path)

    meta_path = os.path.join(OUTPUT_DIR, f"{video_id}_meta.json")
    with open(meta_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"\nDone! Video: {output_path}")
    print(f"Duration: {result.get('duration', '?')}s")


if __name__ == "__main__":
    main()
