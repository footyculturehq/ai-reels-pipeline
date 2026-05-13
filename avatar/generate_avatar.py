#!/usr/bin/env python3
"""
Generate an AI avatar video using SadTalker (free, open source, CUDA accelerated).

Pipeline:
  1. edge-tts generates audio from your script
  2. SadTalker animates your source photo with that audio
  3. Output is an MP4 ready for the pipeline

SadTalker runs in its own Python 3.11 venv at C:/SadTalker/venv/
RTX 5060 Ti detected — generation takes ~1-2 minutes per video.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONFIG_PATH = SCRIPT_DIR / "config.json"

# Python 3.11 venv dedicated to SadTalker (incompatible with Python 3.14)
SADTALKER_PYTHON = Path("C:/SadTalker/venv/Scripts/python.exe")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def generate(script: str, output_path: str, voice: str = None,
             photo_path: str = None, still: bool = True) -> str:
    config = load_config()

    sadtalker_dir = Path(config.get("sadtalker_dir", "C:/SadTalker"))
    if not sadtalker_dir.exists():
        print(f"Error: SadTalker not found at {sadtalker_dir}")
        print("Setup instructions:")
        print("  git clone https://github.com/OpenTalker/SadTalker C:/SadTalker")
        print("  cd C:/SadTalker && pip install -r requirements.txt")
        print("  python scripts/download_models.py")
        print(f"Then update 'sadtalker_dir' in avatar/config.json")
        sys.exit(1)

    FFMPEG_DIR = "C:/Users/kaima/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin"
    env = os.environ.copy()
    env["PATH"] = FFMPEG_DIR + os.pathsep + env.get("PATH", "")

    # Step 0: Prepare photo — random jersey + room background composite
    if photo_path:
        # Explicit override — use as-is
        photo_abs = Path(photo_path) if Path(photo_path).is_absolute() else PROJECT_DIR / photo_path
        if not photo_abs.exists():
            print(f"Error: Source photo not found at {photo_abs}")
            sys.exit(1)
    else:
        print("Step 0/3: Preparing avatar photo (jersey + room background)...")
        sys.path.insert(0, str(PROJECT_DIR))
        from avatar.prepare_photo import prepare as prepare_photo
        prepared = prepare_photo(target_size=(512, 512))
        photo_abs = Path(prepared)

    # Step 1: Generate audio (using SadTalker venv which has edge-tts)
    audio_path = SCRIPT_DIR / "output" / "speech.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    print("Step 1/3: Generating audio with edge-tts...")

    tts_script = SCRIPT_DIR / "tts.py"
    tts_voice = voice or config.get("voice", "en-GB-RyanNeural")
    tts_cmd = [
        str(SADTALKER_PYTHON), str(tts_script),
        "--script", script,
        "--output", str(audio_path),
        "--voice", tts_voice,
    ]
    tts_result = subprocess.run(tts_cmd, env=env)
    if tts_result.returncode != 0:
        print("Error: edge-tts failed.")
        sys.exit(1)

    # Step 2: Run SadTalker to get base animated face video
    result_dir = SCRIPT_DIR / "output" / "sadtalker_result"
    result_dir.mkdir(parents=True, exist_ok=True)

    print("Step 2/3: Animating face with SadTalker (~1-2 min on RTX 5060 Ti)...")

    cmd = [
        str(SADTALKER_PYTHON), "inference.py",
        "--driven_audio", str(audio_path),
        "--source_image", str(photo_abs),
        "--result_dir", str(result_dir),
        "--preprocess", "crop",   # crop is sufficient; GFPGAN runs after Wav2Lip
        "--expression_scale", "1.0",
    ]
    if still:
        cmd.append("--still")

    result = subprocess.run(cmd, cwd=str(sadtalker_dir), env=env)
    if result.returncode != 0:
        print("Error: SadTalker failed. Check output above.")
        sys.exit(1)

    mp4_files = list(result_dir.glob("*.mp4"))
    if not mp4_files:
        print("Error: SadTalker ran but no .mp4 found in output.")
        sys.exit(1)

    sadtalker_video = sorted(mp4_files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    print(f"  SadTalker output: {sadtalker_video}")

    # Step 3: Wav2Lip lip sync → GFPGAN quality enhancement
    WAV2LIP_PYTHON = Path("C:/Wav2Lip/venv/Scripts/python.exe")
    WAV2LIP_DIR = Path("C:/Wav2Lip")
    WAV2LIP_CKPT = WAV2LIP_DIR / "checkpoints" / "wav2lip.pth"
    FFMPEG_EXE = Path(FFMPEG_DIR) / "ffmpeg.exe"

    if WAV2LIP_PYTHON.exists() and WAV2LIP_CKPT.exists():
        print("Step 3/3: Wav2Lip lip sync + GFPGAN enhancement...")

        # Wav2Lip needs space-free paths and prefers 480x480 input
        wl_input_video = WAV2LIP_DIR / "temp" / "input_face.mp4"
        wl_input_audio = WAV2LIP_DIR / "temp" / "input_audio.mp3"
        wl_input_480   = WAV2LIP_DIR / "temp" / "input_face_480.mp4"
        wl_output_raw  = WAV2LIP_DIR / "temp" / "output.mp4"
        wl_output_enh  = SCRIPT_DIR / "output" / "wav2lip_enhanced.mp4"

        shutil.copy2(str(sadtalker_video), str(wl_input_video))
        shutil.copy2(str(audio_path), str(wl_input_audio))

        # Resize to 480x480 — Wav2Lip face detection is tuned for this size
        subprocess.run([
            str(FFMPEG_EXE), "-y", "-i", str(wl_input_video),
            "-vf", "scale=480:480", "-c:v", "libx264", "-crf", "18",
            str(wl_input_480)
        ], env=env, capture_output=True)

        wl_cmd = [
            str(WAV2LIP_PYTHON), "inference.py",
            "--checkpoint_path", str(WAV2LIP_CKPT),
            "--face", str(wl_input_480),
            "--audio", str(wl_input_audio),
            "--outfile", str(wl_output_raw),
            "--nosmooth",
        ]
        wl_result = subprocess.run(wl_cmd, cwd=str(WAV2LIP_DIR), env=env)

        if wl_result.returncode == 0 and wl_output_raw.exists():
            # GFPGAN enhancement — upscale 480→960
            enhance_script = SCRIPT_DIR / "enhance_video.py"
            enh_result = subprocess.run([
                "python", str(enhance_script),
                "--input",   str(wl_output_raw),
                "--output",  str(wl_output_enh),
                "--upscale", "2",
            ], env=env)

            if enh_result.returncode == 0 and wl_output_enh.exists():
                final_video = wl_output_enh
                print("  Wav2Lip + GFPGAN complete.")
            else:
                print("  GFPGAN failed — using raw Wav2Lip output.")
                final_video = wl_output_raw
        else:
            print("  Wav2Lip failed — falling back to SadTalker output.")
            final_video = sadtalker_video
    else:
        print("Step 3/3: Wav2Lip not found — using SadTalker output directly.")
        final_video = sadtalker_video

    # Copy final video to requested output path
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    shutil.copy2(str(final_video), output_path)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\nDone! Avatar saved: {output_path} ({size_mb:.1f} MB)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate AI avatar video (SadTalker + edge-tts)")
    parser.add_argument("--script", required=True, help="Script text to speak")
    parser.add_argument("--output", "-o", required=True, help="Output MP4 path")
    parser.add_argument("--voice", help="Edge TTS voice (default from config)")
    parser.add_argument("--photo", help="Source photo path (default from config)")
    parser.add_argument("--no-still", action="store_true", help="Allow more head movement")
    args = parser.parse_args()

    generate(
        script=args.script,
        output_path=args.output,
        voice=args.voice,
        photo_path=args.photo,
        still=not args.no_still,
    )


if __name__ == "__main__":
    main()
