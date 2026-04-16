#!/bin/sh
# End-to-end smoke tests using Python urllib only — no curl, no nc.
#
# M6 findings applied:
#   - /health returns {"status": "healthy"} not {"status": "ok"}
#   - Search endpoint is POST /api/search/semantic
#   - Search body uses max_results (not limit)
#   - Search response is nested {"tools": [...], "servers": [...], ...}
# M3 findings applied:
#   - X-Username + X-Auth-Method: network-trusted headers bypass nginx JWT auth
set -e

GATEWAY_URL="${GATEWAY_BASE_URL:-http://localhost:7860}"

python3 - <<PYEOF
import urllib.request
import json
import sys

gateway_url = "${GATEWAY_URL}"
passed = 0
failed = 0

# M3: network-trusted headers bypass nginx JWT validation
trusted_headers = {
    "X-Username": "validate-script",
    "X-Auth-Method": "network-trusted",
}

def check(label, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  PASS: {label}")
        passed += 1
    else:
        print(f"  FAIL: {label}" + (f" — {detail}" if detail else ""))
        failed += 1

print("\n=== PoC Smoke Tests ===\n")

# 1. Gateway health
print("[1] Gateway health")
try:
    with urllib.request.urlopen(f"{gateway_url}/health", timeout=5) as r:
        body = json.loads(r.read())
        # M6: status is "healthy" not "ok"
        status = body.get("status", "")
        check("GET /health returns 200 with status healthy/ok",
              status in ("healthy", "ok", "up"))
except Exception as e:
    check("GET /health", False, str(e))

# 2. List servers
print("\n[2] Registered servers")
try:
    req = urllib.request.Request(
        f"{gateway_url}/api/servers",
        headers=trusted_headers,
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
        servers = data if isinstance(data, list) else data.get("servers", [])
        names = {s.get("display_name", s.get("server_name", "")) for s in servers}
        check("github-mcp registered", "github-mcp" in names)
        check("jira-mcp registered", "jira-mcp" in names)
        check("At least one tool indexed in github-mcp",
              any(s.get("display_name", s.get("server_name")) == "github-mcp"
                  and len(s.get("tool_list") or []) > 0
                  for s in servers))
except Exception as e:
    check("GET /api/servers", False, str(e))

# 3. Semantic search (M6: endpoint is /api/search/semantic, param is max_results)
print("\n[3] Semantic search")
queries = [
    ("create a github issue for a bug", ["issue", "ticket"]),
    ("search jira tickets by project",  ["ticket", "jira"]),
]
for query, keywords in queries:
    try:
        data = json.dumps({"query": query, "max_results": 3}).encode()
        req = urllib.request.Request(
            f"{gateway_url}/api/search/semantic",
            data=data,
            headers={"Content-Type": "application/json", **trusted_headers},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
            # M6: results are nested in {"tools": [...], "servers": [...], ...}
            all_results = body.get("tools", []) + body.get("servers", [])
            relevant = any(
                any(kw in str(t.get("tool_name","")).lower() or
                    kw in str(t.get("description","")).lower() or
                    kw in str(t.get("server_name","")).lower()
                    for kw in keywords)
                for t in all_results
            )
            check(f'Search "{query[:40]}..." returns relevant tool', relevant,
                  f"got {[t.get('tool_name', t.get('server_name')) for t in all_results]}")
    except Exception as e:
        check(f'Search "{query[:40]}..."', False, str(e))

print(f"\n=== Result: {passed} passed, {failed} failed ===\n")
if failed > 0:
    sys.exit(1)
PYEOF
