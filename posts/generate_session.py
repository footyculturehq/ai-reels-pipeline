"""
generate_session.py — run this ONCE on your local machine to create
posts/instagram_session.json, then commit that file to the repo.

GitHub Actions uses data-centre IPs that Instagram blocks for fresh logins.
Pre-generating the session from a residential IP lets Actions reuse the
authenticated cookies without ever triggering a new login request.

Usage:
  pip install instagrapi
  python posts/generate_session.py
  git add posts/instagram_session.json
  git commit -m "chore: add instagram session"
  git push
"""

import getpass
import sys
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "instagram_session.json"


def main() -> None:
    try:
        from instagrapi import Client
    except ImportError:
        print("ERROR: instagrapi not installed. Run:  pip install instagrapi")
        sys.exit(1)

    print("=== Instagram Session Generator ===")
    print("Log in once from this machine so GitHub Actions can reuse your session.\n")

    username = input("Instagram username (e.g. footyculturehq): ").strip()
    password = getpass.getpass("Instagram password: ")

    cl = Client()
    cl.set_locale("en_US")
    cl.set_timezone_offset(0)

    print(f"\nLogging in as @{username} …")
    try:
        cl.login(username, password)
    except Exception as exc:
        print(f"\nERROR: Login failed — {exc}")
        print("\nIf Instagram is asking for a verification code, check your email/app.")
        sys.exit(1)

    cl.dump_settings(str(SESSION_FILE))
    print(f"\nSession saved to: {SESSION_FILE}")
    print("\nNext steps:")
    print("  git add posts/instagram_session.json")
    print('  git commit -m "chore: add instagram session"')
    print("  git push")
    print("\nGitHub Actions will now reuse this session to post without re-logging in.")


if __name__ == "__main__":
    main()
