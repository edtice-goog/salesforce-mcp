"""One-time (re)authorization for the Salesforce MCP server.

Opens your default browser to the org's standard Salesforce login page
(OAuth 2.0 web-server flow with PKCE), catches the redirect on
http://localhost:1717/OauthRedirect, exchanges the code for tokens, and
saves them for server.py to use. Your password is only ever typed into
Salesforce's own login page in your browser.

Usage:
    py login.py [--login-url https://sig-synopsys.my.salesforce.com] [--timeout 1800]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

import auth


def make_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class _Callback(http.server.BaseHTTPRequestHandler):
    result: dict = {}
    expected_state: str = ""
    done = threading.Event()

    def do_GET(self):  # noqa: N802 — http.server API
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != auth.REDIRECT_PATH:
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        if params.get("state", [""])[0] != _Callback.expected_state:
            self.send_error(400, "state mismatch")
            return
        _Callback.result = {k: v[0] for k, v in params.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in _Callback.result
        msg = (
            "Salesforce authorization complete. You can close this tab."
            if ok else
            "Salesforce authorization failed - see the terminal for details."
        )
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())
        _Callback.done.set()

    def log_message(self, *args):  # silence per-request logging
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login-url", default=auth.DEFAULT_LOGIN_URL)
    ap.add_argument("--timeout", type=int, default=1800,
                    help="seconds to wait for the browser login (default 30 min)")
    args = ap.parse_args()
    login_url = args.login_url.rstrip("/")

    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    _Callback.expected_state = state

    q = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": auth.CLIENT_ID,
        "redirect_uri": auth.REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "prompt": "login",
    })
    authorize_url = f"{login_url}/services/oauth2/authorize?{q}"

    server = http.server.HTTPServer(("127.0.0.1", auth.REDIRECT_PORT), _Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"Opening browser for Salesforce login at {login_url} ...")
    print("If no browser opens, paste this URL into one:\n")
    print(authorize_url + "\n")
    webbrowser.open(authorize_url)

    if not _Callback.done.wait(timeout=args.timeout):
        print("Timed out waiting for the browser login.", file=sys.stderr)
        server.shutdown()
        return 1
    server.shutdown()

    if "code" not in _Callback.result:
        print(f"Authorization failed: {_Callback.result}", file=sys.stderr)
        return 1

    data = {
        "grant_type": "authorization_code",
        "client_id": auth.CLIENT_ID,
        "redirect_uri": auth.REDIRECT_URI,
        "code": _Callback.result["code"],
        "code_verifier": verifier,
    }
    if auth.CLIENT_SECRET:
        data["client_secret"] = auth.CLIENT_SECRET
    resp = auth.post_form(f"{login_url}/services/oauth2/token", data)

    tokens = {
        "login_url": login_url,
        "client_id": auth.CLIENT_ID,
        "access_token": resp["access_token"],
        "refresh_token": resp.get("refresh_token", ""),
        "instance_url": resp.get("instance_url", login_url),
        "identity_url": resp.get("id", ""),
    }
    if auth.CLIENT_SECRET:
        tokens["client_secret"] = auth.CLIENT_SECRET

    # Fetch the username so the success message says who is connected.
    try:
        req = urllib.request.Request(
            f"{login_url}/services/oauth2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            info = json.loads(r.read().decode())
        tokens["username"] = info.get("preferred_username", "")
    except Exception:
        tokens["username"] = ""

    auth.save_tokens(tokens)
    who = tokens["username"] or "(username unknown)"
    print(f"Authorized as {who}. Tokens saved to {auth.TOKEN_FILE}")
    if not tokens["refresh_token"]:
        print("WARNING: no refresh token was returned; you will need to re-run "
              "login.py when the access token expires.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
