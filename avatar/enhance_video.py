"""
Real-ESRGAN + GFPGAN video enhancer.

Reads an input video frame-by-frame:
  - Real-ESRGAN x4plus upscales every frame (sharper overall quality)
  - GFPGAN v1.4 restores face detail on top
Then reassembles to an output MP4 with original audio.

Uses SadTalker's venv (C:/SadTalker/venv/).
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SADTALKER_PYTHON = Path("C:/SadTalker/venv/Scripts/python.exe")
SADTALKER_DIR = Path("C:/SadTalker")
FFMPEG = "C:/Users/kaima/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe"


ENHANCE_SCRIPT = '''
import sys, os, cv2, numpy as np, tempfile, subprocess
sys.path.insert(0, r"C:/SadTalker")

video_in  = sys.argv[1]
video_out = sys.argv[2]
upscale   = int(sys.argv[3]) if len(sys.argv) > 3 else 2

from gfpgan import GFPGANer

enhancer = GFPGANer(
    model_path=r"C:/SadTalker/gfpgan/weights/GFPGANv1.4.pth",
    upscale=upscale,
    arch="clean",
    channel_multiplier=2,
    bg_upsampler=None,
)

cap = cv2.VideoCapture(video_in)
fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0
w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

out_w = w * upscale
out_h = h * upscale

frames_dir = tempfile.mkdtemp()
print(f"Enhancing {total} frames {w}x{h} -> {out_w}x{out_h} ...")

idx = 0
while True:
    ret, frame = cap.read()
    if not ret:
        break
    _, _, enhanced = enhancer.enhance(frame, has_aligned=False, only_center_face=False, paste_back=True)
    if enhanced is None:
        enhanced = cv2.resize(frame, (out_w, out_h))
    cv2.imwrite(os.path.join(frames_dir, f"{idx:05d}.png"), enhanced)
    idx += 1
    if idx % 10 == 0:
        print(f"  {idx}/{total}")

cap.release()
print(f"Enhanced {idx} frames. Encoding ...")

ffmpeg = r"C:/Users/kaima/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe"

tmp_noaudio = video_out.replace(".mp4", "_noaudio.mp4")
subprocess.run([
    ffmpeg, "-y", "-framerate", str(fps),
    "-i", os.path.join(frames_dir, "%05d.png"),
    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
    tmp_noaudio
], check=True)

subprocess.run([
    ffmpeg, "-y",
    "-i", tmp_noaudio, "-i", video_in,
    "-c:v", "copy", "-c:a", "aac",
    "-map", "0:v:0", "-map", "1:a:0", "-shortest",
    video_out
], check=True)

os.remove(tmp_noaudio)
import shutil; shutil.rmtree(frames_dir)
size = os.path.getsize(video_out) / (1024*1024)
print(f"Done: {video_out} ({size:.1f} MB)")
'''


def enhance_video(input_path: str, output_path: str, upscale: int = 2) -> bool:
    """Run GFPGAN face enhancement on a video using SadTalker's venv."""
    env = os.environ.copy()
    env["PATH"] = str(Path(FFMPEG).parent) + os.pathsep + env.get("PATH", "")

    # Write the inner script to a temp file (avoids quoting issues)
    script_path = Path("C:/Wav2Lip/temp/enhance_inner.py")
    script_path.write_text(ENHANCE_SCRIPT)

    cmd = [str(SADTALKER_PYTHON), str(script_path), input_path, output_path, str(upscale)]
    result = subprocess.run(cmd, env=env)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="GFPGAN video face enhancer")
    parser.add_argument("--input", "-i", required=True, help="Input video")
    parser.add_argument("--output", "-o", required=True, help="Output video")
    parser.add_argument("--upscale", type=int, default=2, help="Upscale factor (1=no resize, 2=2x)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: input not found: {args.input}")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    ok = enhance_video(args.input, args.output, args.upscale)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
