"""HeyGen API client wrapper. Handles auth, video generation, polling, and download."""

import requests
import time
import json
import os

API_BASE = "https://api.heygen.com"
UPLOAD_BASE = "https://upload.heygen.com"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "heygen_config.json")


def load_api_key():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Missing {CONFIG_PATH}")
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    key = config.get("api_key", "")
    if not key or key == "YOUR_HEYGEN_API_KEY":
        raise ValueError("Set your real HeyGen API key in heygen_config.json")
    return key


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_profile(profile_name):
    config = load_config()
    profiles = config.get("profiles", {})
    if profile_name not in profiles:
        available = ", ".join(profiles.keys()) or "(none)"
        raise ValueError(f"Unknown profile '{profile_name}'. Available: {available}")
    return profiles[profile_name]


def headers(api_key=None):
    key = api_key or load_api_key()
    return {
        "X-Api-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def list_avatars(api_key=None):
    resp = requests.get(f"{API_BASE}/v2/avatars", headers=headers(api_key))
    resp.raise_for_status()
    return resp.json()


def list_voices(api_key=None):
    resp = requests.get(f"{API_BASE}/v2/voices", headers=headers(api_key))
    resp.raise_for_status()
    return resp.json()


def generate_video(
    script, avatar_id, voice_id, title="Test Video",
    dimension=None, background=None, avatar_style="normal",
    voice_speed=1.0, voice_emotion=None, callback_url=None, api_key=None,
):
    if dimension is None:
        dimension = {"width": 1080, "height": 1920}
    if background is None:
        background = {"type": "color", "value": "#000000"}

    voice_config = {
        "type": "text",
        "voice_id": voice_id,
        "input_text": script,
        "speed": voice_speed,
    }
    if voice_emotion:
        voice_config["emotion"] = voice_emotion

    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": avatar_id,
                "avatar_style": avatar_style,
            },
            "voice": voice_config,
            "background": background,
        }],
        "dimension": dimension,
        "title": title,
    }
    if callback_url:
        payload["callback_url"] = callback_url

    resp = requests.post(f"{API_BASE}/v2/video/generate", headers=headers(api_key), json=payload)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"HeyGen error: {data['error']}")

    video_id = data["data"]["video_id"]
    print(f"Video generation started: {video_id}")
    return video_id


def check_status(video_id, api_key=None):
    resp = requests.get(
        f"{API_BASE}/v1/video_status.get",
        params={"video_id": video_id},
        headers=headers(api_key),
    )
    resp.raise_for_status()
    return resp.json()["data"]


def wait_for_video(video_id, poll_interval=15, timeout=600, api_key=None):
    start = time.time()
    last_status = None
    while time.time() - start < timeout:
        data = check_status(video_id, api_key)
        status = data.get("status")
        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"  [{elapsed}s] Status: {status}")
            last_status = status
        if status == "completed":
            print(f"  Video ready! Duration: {data.get('duration', '?')}s")
            return data
        if status == "failed":
            raise RuntimeError(f"Video generation failed: {data.get('error', 'unknown')}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Video not ready after {timeout}s")


def download_video(video_url, output_path):
    print(f"  Downloading to {output_path}...")
    resp = requests.get(video_url, stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  Downloaded: {size_mb:.1f} MB")
    return output_path
