"""Authorize the Salesforce MCP server via the OAuth 2.0 device flow.

No localhost redirect needed: this prints a short user code and a Salesforce
verification URL; sign in there (any browser) and confirm the code. The
script polls until Salesforce reports the grant, then saves tokens for
server.py. Your password is only ever typed into Salesforce's own login page.

Usage:
    py login_device.py [--login-url https://sig-synopsys.my.salesforce.com] [--timeout 1200]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import auth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login-url", default=auth.DEFAULT_LOGIN_URL)
    ap.add_argument("--timeout", type=int, default=1200,
                    help="seconds to wait for the user to confirm (default 20 min)")
    args = ap.parse_args()
    login_url = args.login_url.rstrip("/")
    token_url = f"{login_url}/services/oauth2/token"

    init = auth.post_form(token_url, {
        "response_type": "device_code",
        "client_id": auth.CLIENT_ID,
    })
    user_code = init["user_code"]
    verification_uri = init.get("verification_uri", f"{login_url}/setup/connect")
    interval = int(init.get("interval", 5))

    print(f"USER_CODE: {user_code}", flush=True)
    print(f"VERIFY_URL: {verification_uri}?user_code={user_code}", flush=True)
    print("Waiting for you to sign in and confirm the code...", flush=True)

    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(interval)
        try:
            resp = auth.post_form(token_url, {
                "grant_type": "device",
                "client_id": auth.CLIENT_ID,
                "code": init["device_code"],
            })
        except auth.AuthError as e:
            msg = str(e)
            if "authorization_pending" in msg:
                continue
            if "slow_down" in msg:
                interval += 5
                continue
            print(f"Authorization failed: {msg}", file=sys.stderr, flush=True)
            return 1
        tokens = {
            "login_url": login_url,
            "client_id": auth.CLIENT_ID,
            "access_token": resp["access_token"],
            "refresh_token": resp.get("refresh_token", ""),
            "instance_url": resp.get("instance_url", login_url),
            "identity_url": resp.get("id", ""),
        }
        try:
            req = urllib.request.Request(
                f"{login_url}/services/oauth2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                tokens["username"] = json.loads(r.read().decode()).get("preferred_username", "")
        except Exception:
            tokens["username"] = ""
        auth.save_tokens(tokens)
        who = tokens["username"] or "(username unknown)"
        print(f"Authorized as {who}. Tokens saved to {auth.TOKEN_FILE}", flush=True)
        if not tokens["refresh_token"]:
            print("WARNING: no refresh token returned; re-auth will be needed "
                  "when the access token expires.", file=sys.stderr, flush=True)
        return 0

    print("Timed out waiting for device-flow confirmation.", file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
