"""Refresh the long-lived Instagram access token (valid 60 days).

Prints the new token. Run with the current token in IG_ACCESS_TOKEN.
The refresh workflow uses this to keep the repo secret up to date.
"""

import os
import sys

import requests


def main() -> None:
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("Missing IG_ACCESS_TOKEN", file=sys.stderr)
        sys.exit(1)

    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=30,
    ).json()

    new_token = resp.get("access_token")
    if not new_token:
        print(f"Refresh failed: {resp}", file=sys.stderr)
        sys.exit(1)

    print(new_token)


if __name__ == "__main__":
    main()
