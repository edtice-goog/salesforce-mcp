"""salesforce MCP server — read-only access to the sig-synopsys Salesforce org
via the REST API.

All tools issue GET requests only (query/describe/search/fetch); nothing here
can create, update, or delete Salesforce data.

Auth: OAuth tokens stored by login.py (see that file); access tokens are
refreshed automatically when they expire.

Usage:
    # Smoke test without MCP (prints identity + a sample query):
    py server.py --selftest

    # Run as an MCP server over STDIO (how Claude Desktop launches it):
    py server.py
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import auth
from mcp.server.fastmcp import FastMCP

FALLBACK_API_VERSION = "v62.0"
_api_version: str | None = None

mcp = FastMCP("salesforce")


# --- REST plumbing ----------------------------------------------------------

def _raw_get(tokens: dict, path: str, params: dict | None = None) -> Any:
    """GET a REST path (absolute or relative to the instance), parsed JSON."""
    url = path if path.startswith("http") else tokens["instance_url"].rstrip("/") + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def sf_get(path: str, params: dict | None = None) -> Any:
    """GET with automatic token refresh on 401 and readable Salesforce errors."""
    tokens = auth.load_tokens()
    try:
        return _raw_get(tokens, path, params)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            tokens = auth.refresh_access_token(tokens)
            try:
                return _raw_get(tokens, path, params)
            except urllib.error.HTTPError as e2:
                raise RuntimeError(_describe_http_error(e2)) from None
        raise RuntimeError(_describe_http_error(e)) from None


def _describe_http_error(e: urllib.error.HTTPError) -> str:
    body = e.read().decode(errors="replace")
    try:
        parsed = json.loads(body)
        if isinstance(parsed, list) and parsed:
            body = "; ".join(
                f"{x.get('errorCode', '?')}: {x.get('message', '')}" for x in parsed
            )
    except Exception:
        pass
    return f"Salesforce API error (HTTP {e.code}): {body[:2000]}"


def api_version() -> str:
    """Latest API version the org supports, discovered once per process."""
    global _api_version
    if _api_version is None:
        try:
            versions = sf_get("/services/data")
            _api_version = "v" + max(versions, key=lambda v: float(v["version"]))["version"]
        except Exception:
            _api_version = FALLBACK_API_VERSION
    return _api_version


def _strip_attributes(node: Any) -> Any:
    """Recursively drop the noisy "attributes" wrappers from query results."""
    if isinstance(node, dict):
        return {k: _strip_attributes(v) for k, v in node.items() if k != "attributes"}
    if isinstance(node, list):
        return [_strip_attributes(x) for x in node]
    return node


# --- Tools ------------------------------------------------------------------

@mcp.tool()
def whoami() -> dict:
    """Who the server is connected as: username, org, and instance URL.

    Use this to verify the Salesforce connection is working.
    """
    tokens = auth.load_tokens()
    info = sf_get(tokens["login_url"].rstrip("/") + "/services/oauth2/userinfo")
    return {
        "username": info.get("preferred_username"),
        "display_name": info.get("name"),
        "email": info.get("email"),
        "user_id": info.get("user_id"),
        "organization_id": info.get("organization_id"),
        "instance_url": tokens.get("instance_url"),
        "api_version": api_version(),
    }


@mcp.tool()
def soql_query(soql: str, max_records: int = 200) -> dict:
    """Run a SOQL query (read-only) and return matching records.

    Example: SELECT Id, Name, StageName FROM Opportunity WHERE IsClosed = false
    ORDER BY CloseDate LIMIT 50

    Follows pagination until max_records is reached; if more remain, the
    result includes next_records_url — pass it to soql_query_more.
    """
    data = sf_get(f"/services/data/{api_version()}/query", {"q": soql})
    records = data.get("records", [])
    while not data.get("done") and len(records) < max_records:
        data = sf_get(data["nextRecordsUrl"])
        records.extend(data.get("records", []))
    truncated = len(records) > max_records or not data.get("done")
    return {
        "total_size": data.get("totalSize"),
        "returned": min(len(records), max_records),
        "records": _strip_attributes(records[:max_records]),
        "next_records_url": None if data.get("done") else data.get("nextRecordsUrl"),
        "truncated": truncated,
    }


@mcp.tool()
def soql_query_more(next_records_url: str, max_records: int = 200) -> dict:
    """Fetch the next page of an earlier soql_query using its next_records_url."""
    data = sf_get(next_records_url)
    records = data.get("records", [])
    while not data.get("done") and len(records) < max_records:
        data = sf_get(data["nextRecordsUrl"])
        records.extend(data.get("records", []))
    return {
        "returned": min(len(records), max_records),
        "records": _strip_attributes(records[:max_records]),
        "next_records_url": None if data.get("done") else data.get("nextRecordsUrl"),
    }


@mcp.tool()
def sosl_search(sosl: str, max_records: int = 100) -> dict:
    """Run a raw SOSL full-text search (read-only).

    Example: FIND {Acme} IN NAME FIELDS RETURNING
    Account(Id, Name), Contact(Id, Name, Email) LIMIT 20
    """
    data = sf_get(f"/services/data/{api_version()}/search", {"q": sosl})
    records = data.get("searchRecords", [])
    out: list[dict] = []
    for r in records[:max_records]:
        obj_type = (r.get("attributes") or {}).get("type")
        r = _strip_attributes(r)
        r["_object"] = obj_type
        out.append(r)
    return {"returned": len(out), "records": out}


@mcp.tool()
def list_objects(name_contains: str = "", include_custom_only: bool = False) -> dict:
    """List queryable Salesforce objects (name + label), optionally filtered.

    name_contains filters case-insensitively against both API name and label.
    """
    data = sf_get(f"/services/data/{api_version()}/sobjects")
    needle = name_contains.lower()
    out = []
    for s in data.get("sobjects", []):
        if not s.get("queryable"):
            continue
        if include_custom_only and not s.get("custom"):
            continue
        if needle and needle not in s["name"].lower() and needle not in s.get("label", "").lower():
            continue
        out.append({"name": s["name"], "label": s.get("label"), "custom": s.get("custom")})
    return {"count": len(out), "objects": out}


@mcp.tool()
def describe_object(object_name: str, field_name_contains: str = "") -> dict:
    """Fields and child relationships of one object (e.g. Account, Case).

    Returns each field's API name, label, type, and for picklists the active
    values; for reference fields the target object(s). field_name_contains
    filters fields case-insensitively.
    """
    data = sf_get(f"/services/data/{api_version()}/sobjects/{object_name}/describe")
    needle = field_name_contains.lower()
    fields = []
    for f in data.get("fields", []):
        if needle and needle not in f["name"].lower() and needle not in f.get("label", "").lower():
            continue
        entry: dict[str, Any] = {
            "name": f["name"],
            "label": f.get("label"),
            "type": f.get("type"),
        }
        if f.get("type") in ("picklist", "multipicklist"):
            entry["picklist_values"] = [
                p["value"] for p in f.get("picklistValues", []) if p.get("active")
            ][:40]
        if f.get("referenceTo"):
            entry["references"] = f["referenceTo"]
            entry["relationship_name"] = f.get("relationshipName")
        if f.get("calculated"):
            entry["calculated"] = True
        fields.append(entry)
    children = [
        {
            "child_object": c.get("childSObject"),
            "relationship_name": c.get("relationshipName"),
            "field": c.get("field"),
        }
        for c in data.get("childRelationships", [])
        if c.get("relationshipName")
    ]
    return {
        "name": data.get("name"),
        "label": data.get("label"),
        "custom": data.get("custom"),
        "field_count": len(fields),
        "fields": fields,
        "child_relationships": children,
    }


@mcp.tool()
def get_record(object_name: str, record_id: str, fields: str = "") -> dict:
    """Fetch one record by its 15/18-character Salesforce Id.

    fields is an optional comma-separated list (e.g. "Name,Industry,Owner.Name");
    omit it to get all fields.
    """
    params = {"fields": fields} if fields else None
    data = sf_get(
        f"/services/data/{api_version()}/sobjects/{object_name}/{record_id}", params
    )
    return _strip_attributes(data)


# --- Selftest / entry point -------------------------------------------------

def selftest() -> int:
    try:
        me = whoami()
    except auth.AuthError as e:
        print(f"AUTH NEEDED: {e}", file=sys.stderr)
        return 1
    print(f"Connected as {me['username']} (org {me['organization_id']}) "
          f"at {me['instance_url']}, API {me['api_version']}")
    q = soql_query("SELECT Id, Name FROM Account ORDER BY LastModifiedDate DESC LIMIT 3")
    print(f"Sample query returned {q['returned']} of {q['total_size']} accounts:")
    for r in q["records"]:
        print(f"  {r.get('Id')}  {r.get('Name')}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    mcp.run()
