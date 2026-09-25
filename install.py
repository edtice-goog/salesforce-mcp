"""Register this salesforce MCP server with Claude on Windows.

Adds the server to the Claude desktop app config
(%APPDATA%\\Claude\\claude_desktop_config.json), using this file's own
location, so it works wherever the repo is cloned.

NOTE: the desktop app rewrites that config from memory while running and can
drop entries added externally — run this with the Claude desktop app CLOSED,
then start the app:

    py install.py

To also register for Claude Code sessions (CLI / Code tab), run:

    claude mcp add --scope user salesforce -- py <path-to>\\server.py
"""
import json
import os
from pathlib import Path

CONFIG = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
SERVER = str(Path(__file__).resolve().parent / "server.py")
ENTRY = {"command": "py", "args": [SERVER]}

cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
servers = cfg.setdefault("mcpServers", {})
if servers.get("salesforce") == ENTRY:
    print("salesforce entry already present; nothing to do.")
else:
    servers["salesforce"] = ENTRY
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"Added salesforce MCP server ({SERVER}) to {CONFIG}")
