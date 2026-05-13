#!/usr/bin/env python3
"""Generate cinematic B-roll clips using Google Veo via Gemini API."""

from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

from google import genai
from google.genai import types

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / "config.json"
OUTPUT_DIR = SCRIPT_DIR / "outputs"

MODELS = {
    "veo-3.1-fast": "veo-3.1-fast-generate-preview",
    "veo-3.1": "veo-3.1-generate-preview",
    "veo-3.0-fast": "veo-3.0-fast-generate-001",
}


def generate_clip(client, model_id, prompt, shot_name, variation, output_dir,
                  aspect_ratio="9:16") -> Path | None:
    output_file = output_dir / f"{shot_name}_v{variation}.mp4"
    if output_file.exists():
        print(f"  Skipping (exists): {output_file.name}")
        return output_file

    print(f"  Generating: {shot_name}_v{variation}")
    try:
        operation = client.models.generate_videos(
            model=model_id, prompt=prompt,
            config=types.GenerateVideosConfig(aspect_ratio=aspect_ratio, number_of_videos=1),
        )
        while not operation.done:
            time.sleep(10)
            operation = client.operations.get(operation)

        if not operation.response or not operation.response.generated_videos:
            print(f"  No video returned for {shot_name}")
            return None

        video = operation.response.generated_videos[0]
        video_bytes = client.files.download(file=video.video)
        with open(output_file, "wb") as f:
            f.write(video_bytes)
        size_mb = output_file.stat().st_size / (1024 * 1024)
        print(f"  Saved: {output_file.name} ({size_mb:.1f} MB)")
        return output_file
    except Exception as e:
        print(f"  ERROR generating {shot_name}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Generate B-roll clips via Veo")
    parser.add_argument("shot_list", help="Shot list JSON path")
    parser.add_argument("--model", default="veo-3.1-fast", choices=list(MODELS.keys()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", "-y", action="store_true")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found. Create it with your gemini_api_key.")
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        config = json.load(f)
    with open(args.shot_list) as f:
        shot_list = json.load(f)

    shots = shot_list.get("shots", [])
    style_prefix = shot_list.get("style_prefix", "")
    cost_per_clip = {"veo-3.1-fast": 0.60, "veo-3.1": 1.60}.get(args.model, 0.60)
    cost = len(shots) * cost_per_clip

    print(f"Shot list: {args.shot_list}")
    print(f"Model: {args.model} (${cost_per_clip}/clip)")
    print(f"Shots: {len(shots)}")

    if args.dry_run:
        for shot in shots:
            print(f"  Shot {shot['number']}: {style_prefix} {shot['prompt']}")
        print(f"\nWould generate {len(shots)} clips (~${cost:.2f})")
        return

    if not args.yes:
        answer = input(f"\nGenerate {len(shots)} clips (~${cost:.2f})? [y/N] ")
        if answer.lower() != "y":
            print("Aborted.")
            return

    api_key = config.get("gemini_api_key", "")
    if not api_key or api_key == "YOUR_GOOGLE_API_KEY":
        print("Error: Set gemini_api_key in ai-video-exploration/config.json")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    run_dir = OUTPUT_DIR / f"{shot_list.get('reel_name', 'reel')}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    model_id = MODELS[args.model]
    generated = []
    for i, shot in enumerate(shots):
        if i > 0:
            print(f"  Waiting 60s (rate limit)...")
            time.sleep(60)
        full_prompt = f"{style_prefix} {shot['prompt']}".strip()
        out = generate_clip(
            client, model_id, full_prompt,
            f"shot{shot['number']:02d}_{shot['name']}", 1, run_dir
        )
        if out:
            generated.append(str(out))

    print(f"\nDone! Generated {len(generated)}/{len(shots)} clips")
    print(f"Output: {run_dir}")


if __name__ == "__main__":
    main()
