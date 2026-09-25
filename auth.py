"""OAuth token management for the Salesforce MCP server.

Uses the OAuth 2.0 web-server flow (with PKCE) against the org's my-domain,
with the same public connected app the Salesforce CLI uses ("PlatformCLI"),
so no connected-app setup is needed in most orgs. Tokens are stored in the
user profile and refreshed automatically.

Override the connected app by setting SF_MCP_CLIENT_ID (and, if the app has
a secret, SF_MCP_CLIENT_SECRET) before running login.py and the server.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_LOGIN_URL = os.environ.get(
    "SF_MCP_LOGIN_URL", "https://sig-synopsys.my.salesforce.com"
)
CLIENT_ID = os.environ.get("SF_MCP_CLIENT_ID", "PlatformCLI")
CLIENT_SECRET = os.environ.get("SF_MCP_CLIENT_SECRET", "")
REDIRECT_PORT = 1717
REDIRECT_PATH = "/OauthRedirect"
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}{REDIRECT_PATH}"

TOKEN_FILE = Path.home() / ".salesforce-mcp" / "tokens.json"


class AuthError(RuntimeError):
    pass


def post_form(url: str, data: dict) -> dict:
    """POST application/x-www-form-urlencoded, return parsed JSON body.

    Raises AuthError with Salesforce's error description on OAuth failures.
    """
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            j = json.loads(detail)
            detail = f"{j.get('error')}: {j.get('error_description')}"
        except Exception:
            pass
        raise AuthError(f"OAuth request to {url} failed (HTTP {e.code}): {detail}") from None


def load_tokens() -> dict:
    if not TOKEN_FILE.exists():
        login_script = Path(__file__).resolve().parent / "login.py"
        raise AuthError(
            f"No Salesforce tokens found at {TOKEN_FILE}. Run:  py {login_script}"
        )
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(tokens: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def refresh_access_token(tokens: dict) -> dict:
    """Exchange the refresh token for a new access token and persist it."""
    login_url = tokens.get("login_url", DEFAULT_LOGIN_URL)
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise AuthError(
            "Stored tokens have no refresh_token; re-run login.py to re-authorize."
        )
    data = {
        "grant_type": "refresh_token",
        "client_id": tokens.get("client_id", CLIENT_ID),
        "refresh_token": refresh,
    }
    secret = tokens.get("client_secret", CLIENT_SECRET)
    if secret:
        data["client_secret"] = secret
    resp = post_form(f"{login_url}/services/oauth2/token", data)
    tokens["access_token"] = resp["access_token"]
    if resp.get("instance_url"):
        tokens["instance_url"] = resp["instance_url"]
    # Salesforce may rotate the refresh token depending on app policy.
    if resp.get("refresh_token"):
        tokens["refresh_token"] = resp["refresh_token"]
    save_tokens(tokens)
    return tokens
