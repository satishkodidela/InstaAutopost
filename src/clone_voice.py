"""One-time ElevenLabs voice helper (run locally, never in CI).

Two jobs:
  --list                 print the voices on the account (pick a stock
                         voice_id to start on, or find your cloned one)
  --create sample.wav    Instant-Voice-Clone from your recording and print
                         the new voice_id to set as ELEVEN_LABS_VOICE_ID

Recording guide for the best Telangana result (this matters more than length):
  * 1-2 minutes, clean audio, one quiet room, no music/echo/background noise.
  * Speak in YOUR natural Telangana Telugu — the clone copies the accent and
    timbre of the sample, so an English sample would make it mispronounce
    Telugu. Read a few recipe-style lines the way you'd narrate a reel.
  * WAV or MP3 is fine. Do not exceed ~3 minutes.

Usage:
  export ELEVEN_LABS_API_KEY=...        # or add it to .env
  python src/clone_voice.py --list
  python src/clone_voice.py --create my_telangana_sample.wav --name "Satish Telangana"
"""

import argparse
import os
import sys

import requests

BASE = "https://api.elevenlabs.io/v1"


def _key() -> str:
    key = os.environ.get("ELEVEN_LABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("Set ELEVEN_LABS_API_KEY (env or .env) first.")
    return key


def list_voices() -> None:
    resp = requests.get(f"{BASE}/voices", headers={"xi-api-key": _key()}, timeout=30)
    resp.raise_for_status()
    for v in resp.json().get("voices", []):
        labels = v.get("labels") or {}
        tags = " ".join(filter(None, [labels.get("language", ""), labels.get("accent", "")]))
        print(f"{v['voice_id']}  {v.get('name', '')}  [{v.get('category', '')}] {tags}")


def create_voice(sample: str, name: str) -> None:
    if not os.path.exists(sample):
        sys.exit(f"Sample not found: {sample}")
    with open(sample, "rb") as fh:
        resp = requests.post(
            f"{BASE}/voices/add",
            headers={"xi-api-key": _key()},
            data={"name": name, "labels": '{"language": "te", "accent": "telangana"}'},
            files=[("files", (os.path.basename(sample), fh, "audio/wav"))],
            timeout=180,
        )
    if not resp.ok:
        sys.exit(f"Clone failed: {resp.status_code} {resp.text[:400]}")
    voice_id = resp.json().get("voice_id")
    print(f"\nCloned. Set this and re-run a reel:\n  ELEVEN_LABS_VOICE_ID={voice_id}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="ElevenLabs voice list / instant clone")
    ap.add_argument("--list", action="store_true", help="list voices on the account")
    ap.add_argument("--create", metavar="SAMPLE", help="instant-clone from an audio file")
    ap.add_argument("--name", default="My Telangana Voice", help="name for the cloned voice")
    args = ap.parse_args()

    if args.list:
        list_voices()
    elif args.create:
        create_voice(args.create, args.name)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
