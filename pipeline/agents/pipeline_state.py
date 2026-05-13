"""Pipeline State Manager: tracks per-reel progress across agent stages."""

import json
import os
from datetime import datetime, timezone

PIPELINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PIPELINE_DIR, "agents", "output")
STAGES = ["curate", "storyboard", "veo", "assemble", "review"]


class PipelineState:
    def __init__(self, reel_id: str):
        self.reel_id = reel_id
        self._dir = os.path.join(OUTPUT_DIR, reel_id)
        self._state_path = os.path.join(self._dir, "pipeline-state.json")
        self._data = self._load()

    @property
    def reel_dir(self) -> str:
        return self._dir

    def _load(self) -> dict:
        if os.path.exists(self._state_path):
            with open(self._state_path) as f:
                return json.load(f)
        return {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def exists(self) -> bool:
        return bool(self._data)

    def init(self, tool_name: str, transcript_path: str = "",
             avatar_src: str = "", script: str = "", product_url: str = ""):
        os.makedirs(self._dir, exist_ok=True)
        os.makedirs(os.path.join(self._dir, "frames"), exist_ok=True)
        self._data = {
            "reel_id": self.reel_id, "created": self._now(), "updated": self._now(),
            "tool_name": tool_name, "transcript_path": transcript_path,
            "avatar_src": avatar_src, "script": script, "product_url": product_url,
            "speed_factor": 1.1,
            "stages": {stage: {"status": "pending"} for stage in STAGES},
            "iteration": 1, "history": [],
        }
        self.save()

    def get_stage_status(self, stage: str) -> str:
        return self._data.get("stages", {}).get(stage, {}).get("status", "pending")

    def complete_stage(self, stage: str, output_filename: str, summary: dict):
        output_path = os.path.join(self._dir, output_filename)
        stages = self._data.setdefault("stages", {})
        stages[stage] = {
            "status": "completed", "completed_at": self._now(),
            "output_path": output_path, "summary": summary,
        }
        self._data["updated"] = self._now()
        self.save()

    def approve_gate(self, stage: str):
        stages = self._data.get("stages", {})
        if stage in stages:
            stages[stage]["status"] = "approved"
            stages[stage]["approved_at"] = self._now()
            self._data["updated"] = self._now()
            self.save()

    def get_output(self, stage: str) -> dict:
        stage_data = self._data.get("stages", {}).get(stage, {})
        output_path = stage_data.get("output_path", "")
        if output_path and os.path.exists(output_path):
            with open(output_path) as f:
                return json.load(f)
        return {}

    def get_config(self, key: str, default=None):
        return self._data.get(key, default)

    def save(self):
        os.makedirs(self._dir, exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(self._data, f, indent=2)

    def summary(self) -> str:
        lines = [f"Reel: {self.reel_id}", f"Tool: {self._data.get('tool_name', '?')}", ""]
        for stage in STAGES:
            status = self.get_stage_status(stage)
            lines.append(f"  {stage:<12} {status}")
        return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("reel_id")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--tool", help="Tool name (required for --init)")
    parser.add_argument("--transcript", default="")
    parser.add_argument("--avatar", default="")
    parser.add_argument("--script", default="")
    parser.add_argument("--url", default="")
    args = parser.parse_args()

    state = PipelineState(args.reel_id)
    if args.init:
        if not args.tool:
            print("Error: --tool required for --init")
            return
        state.init(tool_name=args.tool, transcript_path=args.transcript,
                   avatar_src=args.avatar, script=args.script, product_url=args.url)
        print(f"Initialized pipeline for: {args.reel_id}")

    if state.exists():
        print(state.summary())
    else:
        print(f"No pipeline found for: {args.reel_id}")


if __name__ == "__main__":
    main()
