# Reels Pipeline

Orchestrate the staged reel production pipeline. Request: $ARGUMENTS

---

## Critical Rules

1. **Max 45 seconds.** Scripts must fit within 45 seconds.
2. **Never double-scale timestamps.** Whisper runs on the sped-up avatar — timestamps are already correct.
3. **No scene overlays.** The `scenes` array must always be empty.
4. **B-roll must match speech.** Every segment must be semantically relevant.
5. **Always run from project root** (`ai-reels-pipeline/`).

---

## Commands

Parse `$ARGUMENTS` to determine the action:

- **`new <name> --script "text" --avatar <path>`** — Initialize pipeline state
- **`curate <reel-id>`** — Run Asset Curator, show manifest, wait for approval
- **`storyboard <reel-id>`** — Run Storyboard Agent (Gemini free tier), show timeline, wait for approval
- **`images <reel-id>`** — Run Image Resolver (Wikipedia, no gate)
- **`pexels <reel-id>`** — Download Pexels stock clips for pexels_search segments
- **`assemble <reel-id> [--render]`** — Build ReelConfig JSON and optionally render
- **`review <reel-id>`** — Post-render QA check
- **`status <reel-id>`** — Show pipeline stage status
- **`full <reel-id>`** — Run all stages with human gates at curate + storyboard

---

## Full Workflow

```bash
# NOTE: Avatar steps use the Python 3.11 venv at C:/SadTalker/venv/
# Pipeline steps use Python 3.14 (default python3)

# 0a+0b. Generate avatar video (TTS + SadTalker, ~1-2 min on RTX 5060 Ti)
cd avatar
python generate_avatar.py --script "Your script here" --output ../public/avatars/avatar-my-reel.mp4

# 0c. Speed up 1.1x
ffmpeg -i ../public/avatars/avatar-my-reel.mp4 \
  -filter_complex "[0:v]setpts=PTS/1.1[v];[0:a]atempo=1.1[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k \
  ../public/avatars/avatar-my-reel-fast.mp4

# 0d. Transcribe (Whisper via SadTalker venv)
C:/SadTalker/venv/Scripts/python transcribe.py ../public/avatars/avatar-my-reel-fast.mp4

# 1. Initialize pipeline
cd ..
python3 -m pipeline.agents.pipeline_state my-reel-v1 --init \
  --tool "My Product" \
  --transcript "public/avatars/avatar-my-reel-fast_transcript.json" \
  --avatar "avatars/avatar-my-reel-fast.mp4" \
  --script "Your script here"

# 2. Curate assets [GATE]
python3 -m pipeline.agents.asset_curator --reel-id my-reel-v1 --tool "My Product"

# 3. Storyboard with Gemini [GATE]
python3 -m pipeline.agents.storyboard --reel-id my-reel-v1

# 4. Download Wikipedia images
python3 -m pipeline.agents.image_resolver --reel-id my-reel-v1

# 5. Download Pexels stock clips (free)
python3 -m pipeline.agents.veo_agent --reel-id my-reel-v1

# 6. Assemble + render
python3 -m pipeline.agents.assembly --reel-id my-reel-v1 --render

# 7. Review
python3 -m pipeline.agents.reviewer --reel-id my-reel-v1
```

---

## Gates (human approval required before proceeding)

1. **After curate**: check `pipeline/agents/output/<reel-id>/asset-manifest.json`
2. **After storyboard**: check `pipeline/agents/output/<reel-id>/storyboard.json`

---

## Render manually

```bash
python3 -c "
import json
config = json.load(open('public/config/reel-config-<reel-id>.json'))
json.dump({'config': config}, open('/tmp/reel-props.json', 'w'))
"
npx remotion render DynamicReel out/<reel-id>.mp4 --codec=h264 --props=/tmp/reel-props.json
```
