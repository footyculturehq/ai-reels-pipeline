"""Reviewer Agent: post-render quality verification with frame analysis."""

from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
OUT_DIR = os.path.join(PROJECT_DIR, "out")

# Thresholds
DARK_FRAME_BRIGHTNESS = 15    # Below this = black frame
DARK_FRAME_VARIANCE = 100     # Below this variance = truly black (not dark UI)
DURATION_TOLERANCE = 1.0      # Seconds
MIN_AUDIO_BITRATE = 64000     # bps


def _ffprobe_info(filepath: str) -> dict:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_streams", "-show_format", filepath]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return {}
        return json.loads(result.stdout)
    except Exception:
        return {}


def _extract_frame(video_path: str, timestamp: float, output_path: str) -> bool:
    try:
        cmd = ["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path,
               "-frames:v", "1", "-q:v", "2", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0 and os.path.exists(output_path)
    except Exception:
        return False


def _get_frame_brightness_and_variance(frame_path: str) -> tuple[float, float]:
    """Returns (mean_brightness, variance) using ffmpeg signalstats."""
    try:
        cmd = ["ffmpeg", "-i", frame_path, "-vf", "signalstats", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        yavg = -1.0
        ydif = -1.0
        for line in result.stderr.split("\n"):
            if "YAVG=" in line:
                try:
                    yavg = float(line.split("YAVG=")[1].split()[0])
                except (ValueError, IndexError):
                    pass
            if "YDIF=" in line:
                try:
                    ydif = float(line.split("YDIF=")[1].split()[0])
                except (ValueError, IndexError):
                    pass
        return yavg, ydif
    except Exception:
        return -1.0, -1.0


def _check_audio(video_path: str) -> dict:
    probe = _ffprobe_info(video_path)
    audio_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        return {"has_audio": False, "bitrate": 0}
    bitrate = int(audio_streams[0].get("bit_rate", 0))
    return {"has_audio": True, "bitrate": bitrate}


def _check_duration(video_path: str, expected_duration: float) -> dict:
    probe = _ffprobe_info(video_path)
    actual = float(probe.get("format", {}).get("duration", 0))
    diff = abs(actual - expected_duration)
    return {
        "actual": round(actual, 2),
        "expected": round(expected_duration, 2),
        "diff": round(diff, 2),
        "ok": diff <= DURATION_TOLERANCE,
    }


def review(reel_id: str, rendered_path: str, config: dict, frames_dir: str) -> dict:
    """Run all quality checks. Returns verdict dict."""
    issues = []
    warnings = []
    checks = {}

    # 1. Check file exists
    if not os.path.exists(rendered_path):
        return {
            "verdict": "fail",
            "issues": [f"Rendered file not found: {rendered_path}"],
            "warnings": [],
            "checks": {},
        }

    # 2. Duration check
    expected_frames = config.get("duration", 0)
    expected_sec = expected_frames / 25.0
    dur_check = _check_duration(rendered_path, expected_sec)
    checks["duration"] = dur_check
    if not dur_check["ok"]:
        issues.append(f"Duration mismatch: got {dur_check['actual']}s, expected {dur_check['expected']}s")

    # 3. Audio check
    audio_check = _check_audio(rendered_path)
    checks["audio"] = audio_check
    if not audio_check["has_audio"]:
        issues.append("No audio track found")
    elif audio_check["bitrate"] < MIN_AUDIO_BITRATE:
        warnings.append(f"Low audio bitrate: {audio_check['bitrate']/1000:.0f}kbps")

    # 4. Frame analysis at segment boundaries
    os.makedirs(frames_dir, exist_ok=True)
    segments = config.get("brollSegments", [])
    frame_issues = []
    frame_warns = []

    sample_timestamps = []
    for seg in segments:
        mid = (seg["startSec"] + seg["endSec"]) / 2
        sample_timestamps.append(mid)

    for i, ts in enumerate(sample_timestamps[:10]):  # Check up to 10 frames
        frame_path = os.path.join(frames_dir, f"frame_{i:02d}_{ts:.1f}s.jpg")
        if _extract_frame(rendered_path, ts, frame_path):
            brightness, variance = _get_frame_brightness_and_variance(frame_path)
            if brightness >= 0 and brightness < DARK_FRAME_BRIGHTNESS:
                # Variance-aware: low variance = truly black, not dark UI
                if variance < DARK_FRAME_VARIANCE:
                    frame_issues.append(f"Black frame at {ts:.1f}s (brightness={brightness:.0f}, var={variance:.0f})")
                else:
                    frame_warns.append(f"Dark frame at {ts:.1f}s (brightness={brightness:.0f}, likely dark UI)")

    checks["frames"] = {
        "sampled": len(sample_timestamps),
        "black_frames": len(frame_issues),
        "dark_ui_frames": len(frame_warns),
    }
    issues.extend(frame_issues)
    warnings.extend(frame_warns)

    # Determine verdict
    if issues:
        verdict = "fail"
    elif warnings:
        verdict = "warn"
    else:
        verdict = "pass"

    return {
        "verdict": verdict,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="Reviewer Agent")
    parser.add_argument("--reel-id", required=True)
    parser.add_argument("--rendered", help="Path to rendered MP4 (auto-detected if omitted)")
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    if not state.exists():
        print(f"Error: No pipeline state for {args.reel_id}")
        sys.exit(1)

    # Find rendered video
    rendered_path = args.rendered
    if not rendered_path:
        rendered_path = os.path.join(OUT_DIR, f"{args.reel_id}.mp4")
        if not os.path.exists(rendered_path):
            assemble_summary = state.get_output("assemble") or {}
            rendered_path = assemble_summary.get("rendered", rendered_path)

    # Load config
    from pipeline.agents.pipeline_state import OUTPUT_DIR
    config_path = os.path.join(
        PROJECT_DIR, "public", "config", f"reel-config-{args.reel_id}.json"
    )
    if not os.path.exists(config_path):
        print(f"Error: Config not found at {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    frames_dir = os.path.join(state.reel_dir, "frames")
    print(f"  Reviewing: {rendered_path}")

    result = review(args.reel_id, rendered_path, config, frames_dir)

    verdict = result["verdict"]
    verdict_symbol = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[verdict]
    print(f"\n  Verdict: {verdict_symbol}")

    if result["issues"]:
        print("  Issues (FAIL):")
        for issue in result["issues"]:
            print(f"    - {issue}")

    if result["warnings"]:
        print("  Warnings:")
        for warn in result["warnings"]:
            print(f"    - {warn}")

    if verdict == "pass":
        print("  All checks passed!")

    checks = result.get("checks", {})
    dur = checks.get("duration", {})
    if dur:
        print(f"  Duration: {dur.get('actual')}s (expected {dur.get('expected')}s)")

    review_path = os.path.join(state.reel_dir, "review.json")
    with open(review_path, "w") as f:
        json.dump(result, f, indent=2)

    state.complete_stage("review", "review.json", {
        "verdict": verdict,
        "issues": len(result["issues"]),
        "warnings": len(result["warnings"]),
    })

    if verdict == "fail":
        print("\n  Fix issues and re-run assembly + render.")
        sys.exit(1)


if __name__ == "__main__":
    main()
