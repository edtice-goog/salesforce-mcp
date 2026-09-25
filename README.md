# salesforce-mcp

Read-only [MCP](https://modelcontextprotocol.io) server for Salesforce, built
for the sig-synopsys org (`https://sig-synopsys.my.salesforce.com`) but
usable against any org. All tools are GET-only — SOQL/SOSL queries, object
describes, and record fetches. **Nothing in this server can write to
Salesforce.**

Auth is the standard Salesforce browser login (OAuth 2.0 web-server flow with
PKCE, via the same public connected app the Salesforce CLI uses), so it works
with SSO/Okta and never sees your password. Tokens are stored in
`~\.salesforce-mcp\tokens.json` and refresh automatically.

## Setup (Windows)

1. **Prereqs:** Python 3.10+ (`py` launcher) and the MCP SDK:

   ```
   py -m pip install mcp
   ```

2. **Clone** this repo anywhere, e.g. `C:\Tools\salesforce-mcp`.

3. **Authorize** (opens your browser to the org's normal login page; sign in
   through SSO as usual):

   ```
   py login.py
   ```

   You should see `Authorized as <you>. Tokens saved to ...`.

4. **Smoke test:**

   ```
   py server.py --selftest
   ```

5. **Register with Claude** — either or both:
   - *Claude desktop app (chat):* close the app, run `py install.py`, start
     the app. (Run it with the app closed — the app rewrites its config file
     from memory while running and can drop the entry.)
   - *Claude Code (CLI / Code tab):*

     ```
     claude mcp add --scope user salesforce -- py C:\path\to\salesforce-mcp\server.py
     ```

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Connection check: username, org id, instance, API version |
| `soql_query` / `soql_query_more` | SOQL queries with pagination |
| `sosl_search` | Raw SOSL full-text search |
| `list_objects` | Queryable objects, filterable by name |
| `describe_object` | Fields, picklist values, relationships for one object |
| `get_record` | One record by 15/18-char Id |

## Configuration

Environment variables (only needed to deviate from the defaults):

- `SF_MCP_LOGIN_URL` — org my-domain login URL (default: sig-synopsys).
- `SF_MCP_CLIENT_ID` / `SF_MCP_CLIENT_SECRET` — use your own Connected App
  instead of the Salesforce CLI's public `PlatformCLI` app. Needed only if
  your org blocks PlatformCLI. Your app needs OAuth callback
  `http://localhost:1717/OauthRedirect` and scopes `api refresh_token`.

Set them before running `login.py` *and* in the environment the server runs
in (for the desktop app, an `"env"` block next to `"command"` in the config).

## Files

- `server.py` — the MCP server (STDIO); `--selftest` for a connection check
- `login.py` — browser OAuth authorization; re-run if tokens are revoked
- `login_device.py` — device-flow variant (no localhost redirect); note the
  sig-synopsys org has device flow disabled for PlatformCLI, so this needs a
  custom Connected App with device flow enabled
- `auth.py` — token storage/refresh
- `install.py` — registers the server in the Claude desktop app config

## Troubleshooting

- **"No Salesforce tokens found"** — run `py login.py`.
- **Login page errors or hangs at the end** — the localhost listener wasn't
  running; `login.py` must stay running until the browser redirect completes.
- **`invalid_grant`/`expired access/refresh token`** — tokens were revoked
  (password change, session policy); re-run `py login.py`.
- **Salesforce tools missing in the desktop app** — the app likely rewrote
  its config; re-run `py install.py` with the app closed.
