"""
LatentSync lip-sync wrapper.

Takes:
  --video  : source talking-head video (from SadTalker, or a looping face video)
  --audio  : speech audio (.wav or .mp3)
  --output : output lip-synced MP4

LatentSync venv: C:/LatentSync/venv/Scripts/python.exe
"""

import argparse
import os
import subprocess
import sys
import shutil
from pathlib import Path

LATENTSYNC_DIR = Path("C:/LatentSync")
LATENTSYNC_PYTHON = LATENTSYNC_DIR / "venv" / "Scripts" / "python.exe"
UNET_CONFIG = LATENTSYNC_DIR / "configs" / "unet" / "stage2_512.yaml"
CKPT_PATH = LATENTSYNC_DIR / "checkpoints" / "latentsync_unet.pt"

# Add FFmpeg to PATH
FFMPEG_DIR = "C:/Users/kaima/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin"


def run_latentsync(video_path: str, audio_path: str, output_path: str,
                   inference_steps: int = 20, guidance_scale: float = 1.5) -> bool:
    """Run LatentSync inference via subprocess."""

    env = os.environ.copy()
    env["PATH"] = FFMPEG_DIR + os.pathsep + env.get("PATH", "")

    cmd = [
        str(LATENTSYNC_PYTHON), "-m", "scripts.inference",
        "--unet_config_path", str(UNET_CONFIG),
        "--inference_ckpt_path", str(CKPT_PATH),
        "--inference_steps", str(inference_steps),
        "--guidance_scale", str(guidance_scale),
        "--enable_deepcache",
        "--video_path", video_path,
        "--audio_path", audio_path,
        "--video_out_path", output_path,
    ]

    print(f"  Running LatentSync ({inference_steps} steps)...")
    result = subprocess.run(cmd, cwd=str(LATENTSYNC_DIR), env=env)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="LatentSync lip-sync")
    parser.add_argument("--video", required=True, help="Input talking-head video")
    parser.add_argument("--audio", required=True, help="Speech audio (wav/mp3)")
    parser.add_argument("--output", "-o", required=True, help="Output MP4 path")
    parser.add_argument("--steps", type=int, default=20, help="Diffusion steps (20=fast, 50=quality)")
    parser.add_argument("--guidance", type=float, default=1.5, help="Guidance scale")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Error: video not found: {args.video}")
        sys.exit(1)
    if not os.path.exists(args.audio):
        print(f"Error: audio not found: {args.audio}")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

    success = run_latentsync(args.video, args.audio, args.output,
                             args.steps, args.guidance)
    if success:
        size_mb = os.path.getsize(args.output) / (1024 * 1024)
        print(f"  Done: {args.output} ({size_mb:.1f} MB)")
    else:
        print("  LatentSync failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
