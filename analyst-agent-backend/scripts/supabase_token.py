"""Print a Supabase access token for an email-and-password account, for the scripts and evals
that call the service as a signed-in person.

    $env:TOKEN = python scripts/supabase_token.py you@example.com

Prompts for the password. Reads SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY from the environment
or from .env. A Google-only account has no password; add one from the app, or sign up a
separate email account for scripting. The token lasts as long as the project's JWT expiry
(an hour by default).
"""

import getpass
import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]


def setting(name: str) -> str:
    value = os.environ.get(name) or dotenv_values(REPO / ".env").get(name)
    if not value:
        raise SystemExit(f"set {name} in the environment or in .env")
    return value


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    email = sys.argv[1]
    password = getpass.getpass(f"Supabase password for {email}: ")

    r = httpx.post(
        f"{setting('SUPABASE_URL').rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={"apikey": setting("SUPABASE_PUBLISHABLE_KEY")},
        json={"email": email, "password": password},
        timeout=15,
    )
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        reason = body.get("msg") or body.get("error_description") or r.text[:200]
        print(f"sign-in failed ({r.status_code}): {reason}", file=sys.stderr)
        return 1

    # Only the token on stdout, so `$env:TOKEN = python ...` captures exactly that.
    print(r.json()["access_token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
