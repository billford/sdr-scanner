#!/usr/bin/env python3
"""
Verify your Facebook Page Access Token before going live.
Run: python check_token.py

Checks:
  - Token is valid
  - Token has required pages_manage_posts scope
  - Token expiry date (long-lived tokens last ~60 days)
  - Page ID resolves correctly
"""
import sys
from datetime import datetime, timezone

import requests

from config import FB_ACCESS_TOKEN, FB_PAGE_ID
from post import get_token_info, GRAPH_BASE

REQUIRED_SCOPE = "pages_manage_posts"


def main():
    print("\n=== Facebook Token Check ===\n")

    if not FB_ACCESS_TOKEN:
        print("FAIL  FB_ACCESS_TOKEN is not set in .env")
        sys.exit(1)

    if not FB_PAGE_ID:
        print("FAIL  FB_PAGE_ID is not set in .env")
        sys.exit(1)

    # Check token validity and expiry
    info = get_token_info()

    if not info["valid"]:
        print(f"FAIL  Token is invalid: {info.get('error', 'unknown')}")
        sys.exit(1)

    print(f" OK   Token is valid")
    print(f" OK   App ID: {info.get('app_id', 'unknown')}")

    expires = info.get("expires_at", "unknown")
    print(f" OK   Expires: {expires}")

    # Warn if expiring within 14 days
    try:
        exp_dt = datetime.fromisoformat(expires)
        days_left = (exp_dt - datetime.now()).days
        if days_left < 14:
            print(f"WARN  Token expires in {days_left} days — refresh soon")
        else:
            print(f" OK   {days_left} days until expiry")
    except Exception:
        pass

    # Check required scope
    scopes = info.get("scopes", [])
    if REQUIRED_SCOPE in scopes:
        print(f" OK   Scope '{REQUIRED_SCOPE}' granted")
    else:
        print(f"FAIL  Missing scope '{REQUIRED_SCOPE}' — re-generate token with this permission")
        print(f"      Current scopes: {', '.join(scopes) or 'none'}")
        sys.exit(1)

    # Verify page ID resolves
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/{FB_PAGE_ID}",
            params={"fields": "name,id", "access_token": FB_ACCESS_TOKEN},
            timeout=10,
        )
        resp.raise_for_status()
        page = resp.json()
        print(f" OK   Page resolved: '{page.get('name')}' (ID: {page.get('id')})")
    except Exception as exc:
        print(f"FAIL  Could not resolve page ID {FB_PAGE_ID}: {exc}")
        sys.exit(1)

    print("\nAll checks passed — ready to post.\n")


if __name__ == "__main__":
    main()
