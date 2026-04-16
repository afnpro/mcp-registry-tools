#!/bin/sh
# Manually registers mock servers in the gateway and enables them for tool indexing.
# Uses Python urllib + pyjwt only — no curl required.
#
# Flow:
#   1. Generate a short-lived internal JWT (signed with SECRET_KEY) to call
#      the /api/internal/register and /api/internal/toggle endpoints.
#      These endpoints bypass CSRF and nginx JWT, which is correct for scripted setup.
#   2. Register each mock server with pre-populated tool_list_json so tools are
#      indexed in FAISS immediately — no live MCP crawl needed at seed time.
#   3. Enable each server (toggle from disabled → enabled) so subsequent health
#      checks can also refresh tool state.

GATEWAY_URL="${GATEWAY_BASE_URL:-http://localhost:7860}"
SECRET_KEY="${SECRET_KEY:-poc-secret-key-change-in-prod}"

python3 - <<PYEOF
import urllib.request
import urllib.parse
import json
import os
import sys
import time

try:
    import jwt as pyjwt
except ImportError:
    print("ERROR: pyjwt not installed. Run: pip install pyjwt")
    sys.exit(1)

gateway_url = "${GATEWAY_URL}"
secret_key  = "${SECRET_KEY}"


def _make_internal_token() -> str:
    """Generate a short-lived internal JWT signed with SECRET_KEY."""
    now = int(time.time())
    claims = {
        "iss": "mcp-auth-server",
        "aud": "mcp-registry",
        "sub": "seed-script",
        "purpose": "internal-api",
        "token_use": "access",
        "iat": now,
        "exp": now + 60,
    }
    return pyjwt.encode(claims, secret_key, algorithm="HS256")


# Tool lists for each mock server.
# These match the tools defined in mock-servers/*/server.py.
GITHUB_TOOLS = [
    {
        "name": "create_issue",
        "description": "Creates a new issue in a GitHub repository. Use this tool to report bugs, request features, or track tasks in GitHub.",
        "input_schema": {"type": "object", "properties": {
            "repo": {"type": "string"}, "title": {"type": "string"},
            "body": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}}
        }, "required": ["repo", "title", "body"]},
    },
    {
        "name": "list_pull_requests",
        "description": "Lists pull requests in a GitHub repository. Returns open or closed pull requests with title, author and status. Use to see what code changes are pending review or recently merged.",
        "input_schema": {"type": "object", "properties": {
            "repo": {"type": "string"}, "state": {"type": "string", "default": "open"}
        }, "required": ["repo"]},
    },
    {
        "name": "get_repository_info",
        "description": "Returns metadata about a GitHub repository. Includes description, language, star count and last commit date.",
        "input_schema": {"type": "object", "properties": {
            "repo": {"type": "string"}
        }, "required": ["repo"]},
    },
    {
        "name": "search_code",
        "description": "Searches for code across GitHub repositories using a text query. Returns file paths and snippets matching the search term. Optionally scoped to a specific repository.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string"}, "repo": {"type": "string"}
        }, "required": ["query"]},
    },
]

JIRA_TOOLS = [
    {
        "name": "create_ticket",
        "description": "Creates a new ticket in a Jira project. Use to track bugs, tasks, stories or epics in Jira. Provide the project key (e.g. PLAT, INFRA), a summary, and optionally the issue type and priority.",
        "input_schema": {"type": "object", "properties": {
            "project_key": {"type": "string"}, "summary": {"type": "string"},
            "description": {"type": "string"}, "issue_type": {"type": "string"},
            "priority": {"type": "string"}
        }, "required": ["project_key", "summary", "description"]},
    },
    {
        "name": "get_ticket",
        "description": "Retrieves details of a specific Jira ticket by its key. Returns summary, description, status, assignee and comments. Example key: PLAT-123",
        "input_schema": {"type": "object", "properties": {
            "ticket_key": {"type": "string"}
        }, "required": ["ticket_key"]},
    },
    {
        "name": "search_tickets",
        "description": "Searches Jira tickets using JQL (Jira Query Language). Use to find tickets by project, status, assignee, sprint or any other criteria. Example JQL: project = PLAT AND status = 'In Progress'",
        "input_schema": {"type": "object", "properties": {
            "jql": {"type": "string"}, "max_results": {"type": "integer", "default": 10}
        }, "required": ["jql"]},
    },
    {
        "name": "transition_ticket",
        "description": "Moves a Jira ticket to a new workflow status. Common transitions: 'In Progress', 'Done', 'In Review', 'Blocked'. Use after completing work or updating ticket progress.",
        "input_schema": {"type": "object", "properties": {
            "ticket_key": {"type": "string"}, "transition": {"type": "string"}
        }, "required": ["ticket_key", "transition"]},
    },
]

servers = [
    {
        "name":        "github-mcp",
        "description": "GitHub MCP server: create issues, list pull requests, search code and get repository info",
        "path":        "/github-mcp",
        # /sse suffix: health_service detects SSE transport from the URL, and mcp_client
        # also honours it directly — no extra supported_transports field needed.
        "proxy_pass_url": "http://github-mcp:8000/sse",
        "supported_transports": "sse",
        "tags": "mock,poc",
        "tools": GITHUB_TOOLS,
    },
    {
        "name":        "jira-mcp",
        "description": "Jira MCP server: create tickets, search with JQL, get ticket details and transition workflow status",
        "path":        "/jira-mcp",
        "proxy_pass_url": "http://jira-mcp:8000/sse",
        "supported_transports": "sse",
        "tags": "mock,poc",
        "tools": JIRA_TOOLS,
    },
]

for server in servers:
    # Fresh token per request (60 s TTL).
    token = _make_internal_token()
    auth_headers = {"Authorization": f"Bearer {token}"}

    # ── Step 1: register with pre-populated tool list ──────────────────────
    print(f"==> Registering {server['name']} at {server['path']}...")
    payload = {
        "name":                server["name"],
        "description":         server["description"],
        "path":                server["path"],
        "proxy_pass_url":      server["proxy_pass_url"],
        "supported_transports": server["supported_transports"],
        "tags":                server["tags"],
        "overwrite":           "true",
        "tool_list_json":      json.dumps(server["tools"]),
        "num_tools":           str(len(server["tools"])),
    }
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"{gateway_url}/api/internal/register",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", **auth_headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"    Registered OK (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"    Register FAILED (HTTP {e.code}): {body[:300]}")
        continue
    except Exception as e:
        print(f"    Register FAILED: {e}")
        continue

    # internal/register auto-enables the server after registration — no extra toggle needed.

print("\n==> Done. Mock servers registered, tools indexed, servers enabled.")
PYEOF
