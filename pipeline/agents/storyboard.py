"""Storyboard Agent: uses Google Gemini (free tier) to plan the visual timeline."""

from __future__ import annotations
import argparse, json, os, re, subprocess, sys

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(PIPELINE_DIR)
PUBLIC_DIR = os.path.join(PROJECT_DIR, "public")

SYSTEM_PROMPT = """You are an expert video editor planning B-roll for a split-screen Instagram Reel for the brand Footy Culture HQ (@footyculturehq).

## Brand Context
Footy Culture HQ is a football boot resell and flip intelligence brand. Content covers:
- Drop alerts, profit breakdowns, flip targets, price analysis, tier lists
- Brands: Nike (Phantom GX, Mercurial), Adidas (Predator, Copa, X Crazyfast), New Balance (Furon, Tekela), Puma (Future, King), Mizuno (Morelia Neo)
- Tone: confident, data-driven, street-smart, real numbers
- Visual style: dark/moody, high-contrast, streetwear hype aesthetic
- Audience: 16-28 year old football fans, boot collectors, flippers, sneakerheads

## Layout
- TOP HALF (960px): B-roll - video clips or images
- BOTTOM HALF (960px): AI avatar speaking the script (always visible)
- A word-by-word caption pill appears at the seam

## B-ROLL VISUAL PHILOSOPHY — READ THIS CAREFULLY
The B-roll must look like premium streetwear/sneaker culture content — NOT generic Google stock footage.
Think: hypebeast aesthetic, close-up product shots, cinematic boots on pitch, hands holding shoes, unboxing energy.

GREAT Pexels searches (specific, visually striking):
- Boot close-ups: "soccer cleats grass closeup", "football boots laces detail", "cleats mud action"
- Hands/product: "sneaker hands unboxing", "shoes collection shelf dark", "trainer close up detail"
- Money/profit: "cash counting hands", "dollar bills stack", "money fan hands"
- Action: "football skills dribbling", "soccer player boots feet grass", "footballer running pitch"
- Hype culture: "sneaker display shelf", "shoe store premium", "limited edition trainers"
- Screen/digital: "phone screen app", "laptop screen graph", "person phone scrolling"

AVOID these generic searches (they look like clipart/stock):
- "football boots collection" (too generic)
- "shoe store retail shelf" (looks like a shop ad)
- "stock market price chart" (looks corporate)
- "sneaker collection display" (too catalogue-like)

## Your job
Given a transcript with timestamps and a list of approved assets, produce a JSON storyboard
that maps every moment of the reel to a specific visual asset.

## Strict rules

### Coverage
- Every second from 0 to total_duration must be covered by exactly one segment (no gaps, no overlaps)
- Segment count: 10-15 segments for a 30-45s reel
- Minimum segment duration: 1.2s, Maximum: 5.0s

### Asset mix
- 60%+ of segments must be video clips (type: "video")
- Maximum 2 screenshot segments total; never two screenshots in a row
- Use pexels_search for ALL segments when no approved assets exist — pick the most visually striking query
- Use image_needed only for specific people/places that need a face/landmark

### Semantic matching
- Every visual MUST relate to what the avatar is saying during that segment
- Read the transcript carefully and match visuals to the spoken content

### Quality
- For video clips, vary videoStartSec to show the most interesting part
- Use Ken Burns zoom: scaleFrom/scaleTo between 1.0 and 1.15 (subtle)
- objectPosition guides attention ("center 25%" = top, "center 75%" = bottom)
- Prefer tight, close-up framing over wide landscape shots

### Banned
- scenes array must ALWAYS be empty []
- No consecutive screenshots
- No generic corporate-looking search queries

## Segment types
- "video": use an asset from the manifest (provide asset_path)
- "screenshot": use an image asset from the manifest (provide asset_path)
- "pexels_search": search Pexels for free stock footage (provide search_query: 2-3 keywords)
- "image_needed": download from Wikipedia (provide image_query and label)

## Output format
Respond with ONLY valid JSON — no markdown fences, no explanation:

{
  "reel_id": "<reel_id>",
  "total_duration": <float>,
  "segment_count": <int>,
  "segments": [
    {
      "type": "video|screenshot|pexels_search|image_needed",
      "asset_path": "<path from manifest, or null for pexels_search/image_needed>",
      "start": <float>,
      "end": <float>,
      "label": "<brief label>",
      "framing": {
        "objectPosition": "center center",
        "scaleFrom": 1.0,
        "scaleTo": 1.05,
        "videoStartSec": 0
      },
      "search_query": "<2-3 keywords for Pexels if type=pexels_search>",
      "image_query": "<Wikipedia search query if type=image_needed>",
      "_speech": "<words spoken during this segment>"
    }
  ]
}"""


def _build_user_prompt(reel_id: str, tool_name: str, transcript: dict,
                       manifest: dict, total_duration: float) -> str:
    segments_text = transcript.get("segments", [])
    transcript_lines = [
        f"  [{s['start']:.2f}s - {s['end']:.2f}s] {s['text']}"
        for s in segments_text
    ]

    approved = [a for a in manifest.get("assets", []) if a.get("approved")]
    videos = [a for a in approved if a.get("type") == "video"]
    screenshots = [a for a in approved if a.get("type") == "screenshot"]

    asset_lines = []
    for a in approved:
        t = a["type"]
        path = a["path"]
        score = a.get("quality_score", "?")
        motion = a.get("motion_score", "")
        dur = a.get("duration_sec", "")
        extras = f", motion={motion}" if motion else ""
        extras += f", dur={dur}s" if dur else ""
        asset_lines.append(f"  [{t}] {path} (quality={score}{extras})")

    return f"""Plan the storyboard for reel: {reel_id}
Tool/product: {tool_name}
Total duration: {total_duration:.2f}s

=== TRANSCRIPT ===
{chr(10).join(transcript_lines)}

=== APPROVED ASSETS ({len(approved)} total: {len(videos)} videos, {len(screenshots)} screenshots) ===
{chr(10).join(asset_lines) if asset_lines else "  (none — use pexels_search and image_needed)"}

=== CONSTRAINTS ===
- Reel duration: {total_duration:.2f}s
- Required: 60%+ video segments, max 2 screenshots, 2-3 pexels_search
- scenes array must be empty
- Every segment must match what's being spoken"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _validate_storyboard(storyboard: dict, total_duration: float) -> list[str]:
    errors = []
    segments = storyboard.get("segments", [])
    if not segments:
        errors.append("No segments")
        return errors

    for i, seg in enumerate(segments):
        if i == 0 and seg["start"] > 0.05:
            errors.append(f"Gap at start: first segment starts at {seg['start']:.2f}s")
        if i > 0:
            gap = seg["start"] - segments[i - 1]["end"]
            if gap > 0.1:
                errors.append(f"Gap of {gap:.2f}s between segments {i-1} and {i}")

    last_end = segments[-1]["end"]
    if abs(last_end - total_duration) > 0.5:
        errors.append(f"Last segment ends at {last_end:.2f}s, expected ~{total_duration:.2f}s")

    for i in range(len(segments) - 1):
        if (segments[i].get("type") == "screenshot" and
                segments[i + 1].get("type") == "screenshot"):
            errors.append(f"Consecutive screenshots at segments {i} and {i+1}")

    video_count = sum(1 for s in segments if s.get("type") in ("video", "pexels_search"))
    if segments and video_count / len(segments) < 0.5:
        errors.append(f"Video ratio too low: {video_count}/{len(segments)} (need 60%+)")

    return errors


def _load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        env_path = os.path.join(PROJECT_DIR, ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("GOOGLE_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
    return key


def run_storyboard(reel_id: str, tool_name: str, transcript: dict,
                   manifest: dict, total_duration: float,
                   model: str = "gemini-2.5-flash") -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: google-genai not installed. Run: pip install google-genai")
        sys.exit(1)

    api_key = _load_api_key()
    if not api_key or api_key == "your_google_api_key_here":
        print("Error: GOOGLE_API_KEY not set in .env")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(reel_id, tool_name, transcript, manifest, total_duration)
    print(f"  Calling Gemini ({model})...")

    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.4,
        ),
    )
    storyboard = _extract_json(response.text)

    # Pin total duration and last segment end to actual video duration
    storyboard["total_duration"] = total_duration
    if storyboard.get("segments"):
        storyboard["segments"][-1]["end"] = total_duration

    errors = _validate_storyboard(storyboard, total_duration)
    if errors:
        print("  Validation warnings:")
        for e in errors:
            print(f"    - {e}")

    return storyboard


def get_avatar_duration(avatar_path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "csv=p=0", avatar_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Storyboard Agent (Gemini)")
    parser.add_argument("--reel-id", required=True)
    parser.add_argument("--model", default="gemini-2.5-flash",
                        help="Gemini model (gemini-2.5-flash is free)")
    args = parser.parse_args()

    from pipeline.agents.pipeline_state import PipelineState
    state = PipelineState(args.reel_id)
    if not state.exists():
        print(f"Error: No pipeline state for {args.reel_id}. Run pipeline_state --init first.")
        sys.exit(1)

    tool_name = state.get_config("tool_name", "")
    transcript_path = state.get_config("transcript_path", "")
    avatar_src = state.get_config("avatar_src", "")

    if not transcript_path or not os.path.exists(transcript_path):
        print(f"Error: transcript not found at {transcript_path}")
        sys.exit(1)

    with open(transcript_path) as f:
        transcript = json.load(f)

    manifest = state.get_output("curate")
    if not manifest:
        print("Error: No asset manifest. Run asset_curator first.")
        sys.exit(1)

    avatar_abs = os.path.join(PUBLIC_DIR, avatar_src) if avatar_src else ""
    if avatar_abs and os.path.exists(avatar_abs):
        total_duration = get_avatar_duration(avatar_abs)
        print(f"  Avatar duration: {total_duration:.2f}s")
    else:
        words = transcript.get("words", [])
        total_duration = words[-1]["end"] if words else 30.0
        print(f"  Using transcript duration: {total_duration:.2f}s")

    storyboard = run_storyboard(
        reel_id=args.reel_id,
        tool_name=tool_name,
        transcript=transcript,
        manifest=manifest,
        total_duration=total_duration,
        model=args.model,
    )

    output_path = os.path.join(state.reel_dir, "storyboard.json")
    with open(output_path, "w") as f:
        json.dump(storyboard, f, indent=2)

    n_seg = len(storyboard.get("segments", []))
    n_pexels = sum(1 for s in storyboard.get("segments", []) if s.get("type") == "pexels_search")
    n_img = sum(1 for s in storyboard.get("segments", []) if s.get("type") == "image_needed")
    print(f"  Segments: {n_seg} | Pexels needed: {n_pexels} | Images needed: {n_img}")
    print(f"  Saved: {output_path}")

    state.complete_stage("storyboard", "storyboard.json", {
        "segments": n_seg,
        "pexels_needed": n_pexels,
        "image_needed": n_img,
        "duration": total_duration,
    })


if __name__ == "__main__":
    main()
