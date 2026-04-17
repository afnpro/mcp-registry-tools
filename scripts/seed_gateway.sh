#!/bin/sh
# Registers mock MCP servers in the gateway and pre-populates their tool lists.
#
# Auth: X-Auth-Method: network-trusted — same mechanism the sync-worker uses.
#       No JWT or Bearer token required; works on the direct FastAPI port (7860).
#
# Flow:
#   1. Register each server via POST /api/servers/register (form data).
#      Pass tool_list_json so FAISS indexes the server immediately.
#      Pass mcp_endpoint explicitly so the gateway connects to /mcp/ (not /sse).
#   2. Trigger a semantic search to warm up the query and verify indexing.

GATEWAY_URL="${GATEWAY_BASE_URL:-http://localhost:7860}"

python3 - <<'PYEOF'
import urllib.request
import urllib.parse
import json
import os
import sys

gateway_url = os.environ.get("GATEWAY_BASE_URL", "http://localhost:7860").rstrip("/")

# M3: network-trusted headers grant full admin access to the FastAPI app directly,
# bypassing the nginx JWT layer (which is not running in this PoC setup).
TRUSTED_HEADERS = {
    "X-Username": "seed-script",
    "X-Auth-Method": "network-trusted",
}

GITHUB_TOOLS = [
    {
        "name": "create_issue",
        "description": "Creates a new issue in a GitHub repository. Use this tool to report bugs, request features, or track tasks in GitHub.",
        "input_schema": {"type": "object", "properties": {
            "repo":   {"type": "string", "description": "Repository in owner/name format"},
            "title":  {"type": "string"},
            "body":   {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
        }, "required": ["repo", "title", "body"]},
    },
    {
        "name": "list_pull_requests",
        "description": "Lists pull requests in a GitHub repository. Returns open or closed PRs with title, author and status. Use to see pending code reviews or recently merged changes.",
        "input_schema": {"type": "object", "properties": {
            "repo":  {"type": "string"},
            "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
        }, "required": ["repo"]},
    },
    {
        "name": "get_repository_info",
        "description": "Returns metadata about a GitHub repository: description, language, star count and last commit date.",
        "input_schema": {"type": "object", "properties": {
            "repo": {"type": "string"},
        }, "required": ["repo"]},
    },
    {
        "name": "search_code",
        "description": "Searches for code across GitHub repositories using a text query. Returns file paths and snippets matching the search term. Optionally scoped to a specific repository.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "repo":  {"type": "string", "description": "Limit search to this repo (optional)"},
        }, "required": ["query"]},
    },
]

JIRA_TOOLS = [
    {
        "name": "create_ticket",
        "description": "Creates a new ticket in a Jira project. Use to track bugs, tasks, stories or epics. Provide the project key (e.g. PLAT, INFRA), a summary, and optionally issue type and priority.",
        "input_schema": {"type": "object", "properties": {
            "project_key": {"type": "string"},
            "summary":     {"type": "string"},
            "description": {"type": "string"},
            "issue_type":  {"type": "string", "default": "Task"},
            "priority":    {"type": "string", "default": "Medium"},
        }, "required": ["project_key", "summary", "description"]},
    },
    {
        "name": "get_ticket",
        "description": "Retrieves details of a specific Jira ticket by its key. Returns summary, description, status, assignee and comments. Example key: PLAT-123.",
        "input_schema": {"type": "object", "properties": {
            "ticket_key": {"type": "string"},
        }, "required": ["ticket_key"]},
    },
    {
        "name": "search_tickets",
        "description": "Searches Jira tickets using JQL (Jira Query Language). Use to find tickets by project, status, assignee, sprint or any other criteria. Example: project = PLAT AND status = 'In Progress'.",
        "input_schema": {"type": "object", "properties": {
            "jql":         {"type": "string"},
            "max_results": {"type": "integer", "default": 10},
        }, "required": ["jql"]},
    },
    {
        "name": "transition_ticket",
        "description": "Moves a Jira ticket to a new workflow status. Common transitions: 'In Progress', 'Done', 'In Review', 'Blocked'. Use after completing work or updating ticket progress.",
        "input_schema": {"type": "object", "properties": {
            "ticket_key": {"type": "string"},
            "transition":  {"type": "string"},
        }, "required": ["ticket_key", "transition"]},
    },
]

servers = [
    {
        "name":                "github-mcp",
        "description":         "GitHub MCP server: create issues, list pull requests, search code and get repository info",
        "path":                "/github-mcp",
        # proxy_pass_url is the base URL; gateway appends /mcp automatically.
        # We also pass mcp_endpoint explicitly to avoid any auto-detection ambiguity.
        "proxy_pass_url":      "http://github-mcp:8000",
        "mcp_endpoint":        "http://github-mcp:8000/mcp/",
        "supported_transports": "streamable-http",
        "tags":                "mock,poc",
        "tools":               GITHUB_TOOLS,
    },
    {
        "name":                "jira-mcp",
        "description":         "Jira MCP server: create tickets, search with JQL, get ticket details and transition workflow status",
        "path":                "/jira-mcp",
        "proxy_pass_url":      "http://jira-mcp:8000",
        "mcp_endpoint":        "http://jira-mcp:8000/mcp/",
        "supported_transports": "streamable-http",
        "tags":                "mock,poc",
        "tools":               JIRA_TOOLS,
    },
]


def register(server: dict) -> bool:
    payload = urllib.parse.urlencode({
        "name":                 server["name"],
        "description":          server["description"],
        "path":                 server["path"],
        "proxy_pass_url":       server["proxy_pass_url"],
        "mcp_endpoint":         server["mcp_endpoint"],
        "supported_transports": server["supported_transports"],
        "tags":                 server["tags"],
        "tool_list_json":       json.dumps(server["tools"]),
        "num_tools":            str(len(server["tools"])),
        "overwrite":            "true",
    }).encode()

    req = urllib.request.Request(
        f"{gateway_url}/api/servers/register",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            **TRUSTED_HEADERS,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"    OK (HTTP {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        print(f"    FAILED (HTTP {e.code}): {e.read().decode()[:300]}")
        return False
    except Exception as e:
        print(f"    FAILED: {e}")
        return False


all_ok = True
for server in servers:
    print(f"==> Registering {server['name']} at {server['path']}...")
    if not register(server):
        all_ok = False

print()

# Quick smoke: semantic search should return at least one mock server.
print("==> Verifying semantic search finds mock servers...")
queries = [
    ("create a github issue for a bug", "github"),
    ("search jira tickets by project",  "jira"),
]
for query, keyword in queries:
    payload = json.dumps({"query": query, "max_results": 10}).encode()
    req = urllib.request.Request(
        f"{gateway_url}/api/search/semantic",
        data=payload,
        headers={"Content-Type": "application/json", **TRUSTED_HEADERS},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            servers_found = body.get("servers", [])
            mock_hit = next(
                (s for s in servers_found if keyword in s.get("server_name", "").lower()),
                None,
            )
            if mock_hit:
                score = mock_hit.get("relevance_score", 0)
                path  = mock_hit.get("path", "?")
                print(f"    PASS: '{query[:35]}...' → {path} (score={score:.3f})")
            else:
                names = [s.get("server_name", "?") for s in servers_found[:3]]
                print(f"    WARN: '{query[:35]}...' did not surface {keyword}-mcp in top 10. Got: {names}")
    except Exception as e:
        print(f"    WARN: search check failed: {e}")

print()
if all_ok:
    print("==> Done. Mock servers registered and indexed.")
    print(f"    Web UI:          {gateway_url}/")
    print(f"    Swagger:         {gateway_url}/docs")
    print(f"    Semantic search: POST {gateway_url}/api/search/semantic")
    print(f"    github-mcp MCP:  http://localhost:8001/mcp/")
    print(f"    jira-mcp MCP:    http://localhost:8002/mcp/")
else:
    print("==> Some registrations failed. Check gateway logs: docker logs mcp-gateway")
    sys.exit(1)
PYEOF
