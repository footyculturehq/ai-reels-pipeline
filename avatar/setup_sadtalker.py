#!/usr/bin/env python3
"""One-time setup helper: clone SadTalker and download model weights."""

import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"
DEFAULT_INSTALL = Path("C:/SadTalker")


def main():
    print("=== SadTalker Setup ===\n")

    install_dir = input(f"Where to install SadTalker? [{DEFAULT_INSTALL}]: ").strip()
    if not install_dir:
        install_dir = str(DEFAULT_INSTALL)
    install_path = Path(install_dir)

    if install_path.exists() and (install_path / "inference.py").exists():
        print(f"SadTalker already exists at {install_path}")
    else:
        print(f"\nCloning SadTalker to {install_path}...")
        result = subprocess.run([
            "git", "clone",
            "https://github.com/OpenTalker/SadTalker",
            str(install_path)
        ])
        if result.returncode != 0:
            print("Error: git clone failed. Make sure git is installed.")
            sys.exit(1)

    print("\nInstalling SadTalker requirements...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=str(install_path)
    )
    if result.returncode != 0:
        print("Warning: Some requirements failed to install. Check output above.")

    print("\nDownloading model weights (~2GB, takes a few minutes)...")
    weights_script = install_path / "scripts" / "download_models.py"
    if weights_script.exists():
        subprocess.run([sys.executable, str(weights_script)], cwd=str(install_path))
    else:
        print("Warning: download_models.py not found. You may need to download weights manually.")
        print("See: https://github.com/OpenTalker/SadTalker#-installation")

    # Update config.json
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    config["sadtalker_dir"] = str(install_path).replace("\\", "/")
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nUpdated avatar/config.json with sadtalker_dir: {install_path}")
    print("\nNext: Add your avatar photo to the path set in avatar/config.json")
    print("Default: ai-reels-pipeline/avatar/photo.jpg")
    print("\nSetup complete!")


if __name__ == "__main__":
    main()
