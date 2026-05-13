#!/usr/bin/env python3
"""Transcribe a video using Whisper with word-level timestamps."""

import argparse
import json
import os
import sys

try:
    import mlx_whisper
    _USE_MLX = True
except ImportError:
    import whisper
    _USE_MLX = False


def transcribe(video_path: str, model_name: str = "base") -> dict:
    if _USE_MLX:
        repo = f"mlx-community/whisper-{model_name}"
        print(f"Transcribing with mlx_whisper ({repo}): {video_path}")
        result = mlx_whisper.transcribe(video_path, path_or_hf_repo=repo, word_timestamps=True)
    else:
        print(f"Loading Whisper model '{model_name}'...")
        model = whisper.load_model(model_name)
        print(f"Transcribing: {video_path}")
        result = model.transcribe(video_path, word_timestamps=True)

    words = []
    for segment in result["segments"]:
        for w in segment.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            })

    segments = []
    for seg in result["segments"]:
        segments.append({
            "text": seg["text"].strip(),
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
        })

    return {"text": result["text"].strip(), "words": words, "segments": segments}


def main():
    parser = argparse.ArgumentParser(description="Transcribe video with word timestamps")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--model", default="base", help="Whisper model size")
    parser.add_argument("--output", "-o", help="Output JSON path")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: {args.video} not found")
        sys.exit(1)

    transcript = transcribe(args.video, args.model)

    output_path = args.output or f"{os.path.splitext(args.video)[0]}_transcript.json"
    with open(output_path, "w") as f:
        json.dump(transcript, f, indent=2)

    print(f"\nTranscript saved: {output_path}")
    print(f"  Words: {len(transcript['words'])}")


if __name__ == "__main__":
    main()
