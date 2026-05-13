#!/usr/bin/env python3
"""Text-to-speech using Microsoft Edge TTS (free, no account needed)."""

import argparse
import asyncio
import json
import os
import sys

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


async def _generate(text: str, voice: str, output_path: str):
    try:
        import edge_tts
    except ImportError:
        print("Error: edge-tts not installed. Run: pip install edge-tts")
        sys.exit(1)

    print(f"  Voice: {voice}")
    print(f"  Output: {output_path}")
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_audio(text: str, output_path: str, voice: str = None) -> str:
    config = load_config()
    voice = voice or config.get("voice", "en-US-AriaNeural")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    asyncio.run(_generate(text, voice, output_path))
    size_kb = os.path.getsize(output_path) / 1024
    print(f"  Audio saved: {output_path} ({size_kb:.0f} KB)")
    return output_path


async def _list_voices():
    try:
        import edge_tts
    except ImportError:
        print("Error: edge-tts not installed. Run: pip install edge-tts")
        sys.exit(1)
    voices = await edge_tts.list_voices()
    en_voices = [v for v in voices if v["Locale"].startswith("en-")]
    for v in en_voices:
        print(f"  {v['ShortName']:40s} {v['Gender']}")


def main():
    parser = argparse.ArgumentParser(description="Generate TTS audio using Edge TTS")
    parser.add_argument("--script", required=True, help="Text to speak")
    parser.add_argument("--output", "-o", required=True, help="Output audio path (.mp3 or .wav)")
    parser.add_argument("--voice", help="Voice name (e.g. en-US-AriaNeural)")
    parser.add_argument("--list-voices", action="store_true", help="List available English voices")
    args = parser.parse_args()

    if args.list_voices:
        asyncio.run(_list_voices())
        return

    generate_audio(args.script, args.output, args.voice)


if __name__ == "__main__":
    main()
