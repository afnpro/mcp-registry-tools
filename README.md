# PoC — MCP Tool Auto-Discovery

> Validates semantic tool auto-discovery across MCP servers using a Dockerized stack.
> Agents find the right tool via natural language query — without receiving all schemas upfront.

![Status](https://img.shields.io/badge/status-poc-orange)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Docker](https://img.shields.io/badge/docker-compose-2496ED)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         docker compose                              │
│                                                                     │
│   ┌─────────────────┐      REST API       ┌───────────────────────┐│
│   │   sync-worker   │◄───────────────────►│   mcp-gateway         ││
│   │  python · cron  │   (poll 30 min)     │  (built from source)  ││
│   │  30 min interval│                     │                       ││
│   └─────────────────┘                     │  ┌─────────────────┐  ││
│            ▲                              │  │   Registry API  │  ││
│            │                              │  │  /api/servers   │  ││
│     polls  │                              │  │  /api/search/   │  ││
│            │                              │  │    semantic     │  ││
│   ┌────────┴────────┐                     │  └────────┬────────┘  ││
│   │  MCP Registry   │                     │           │ tools/list ││
│   │ (golden source) │                     │  ┌────────▼────────┐  ││
│   │ registry.mcp.io │                     │  │  Search Index   │  ││
│   └─────────────────┘                     │  │ all-MiniLM-L6-v2│  ││
│                                           │  └─────────────────┘  ││
│                                           └──────────┬────────────┘│
│                                                      │ tools/list  │
│                                           ┌──────────▼────────────┐│
│                                           │     MCP Servers       ││
│                                           │  github-mcp :8001     ││
│                                           │  jira-mcp   :8002     ││
│                                           └───────────────────────┘│
└──────────────────────────────────────────────────────┬─────────────┘
                                                       │ query · execute
                                               ┌───────▼───────┐
                                               │     Agent     │
                                               │ Claude Code   │
                                               │    Devin      │
                                               └───────────────┘
```

**Data flow:**
1. `sync-worker` polls `registry.modelcontextprotocol.io` every 30 minutes
2. New/updated/removed servers are synced to `mcp-gateway` via REST API
3. `mcp-gateway` crawls `tools/list` from each registered MCP server
4. Tools are embedded with `all-MiniLM-L6-v2` and stored in the Search Index
5. Agent sends a natural language query → receives the top-N most relevant tools
6. Agent executes tools directly through `mcp-gateway`

## Components

| Component | Image / Source | Port | Description |
|---|---|---|---|
| `mcp-gateway` | Built from source (`mcp-gateway-registry` submodule) | `7860` | Central catalog with REST API and semantic search. Built locally via `Dockerfile.gateway` — the `ghcr.io` image is **not used**. |
| `sync-worker` | Built from `./sync-worker` (`python:3.11-slim`) | — | Polls the Official MCP Registry and syncs servers to the gateway. Only custom-coded component. |
| `github-mcp` | Built from `./mock-servers/github-mcp` (`python:3.11-slim`) | `8001` | Mock corporate GitHub MCP server. Exposes `create_issue`, `list_pull_requests`, `get_repository_info`, `search_code`. |
| `jira-mcp` | Built from `./mock-servers/jira-mcp` (`python:3.11-slim`) | `8002` | Mock corporate Jira MCP server. Exposes `create_ticket`, `get_ticket`, `search_tickets`, `transition_ticket`. |

### Key technical choices

| Choice | Rationale |
|---|---|
| `mcp-gateway-registry` built from source | Pre-built image is on `ghcr.io` (blocked). Source cloned via git submodule and built with `python:3.11-slim` + pip/uv only. |
| `all-MiniLM-L6-v2` for embeddings | ~90MB, runs locally with no external API dependency. Good cost/benefit for English tool descriptions. |
| `Official MCP Registry` as golden source | Public REST API with no auth required. `updatedAt` field enables efficient incremental sync. Same OpenAPI spec can be replicated internally for production. |
| File-based storage | Simplest possible persistence for PoC — no database container needed. |
| `X-Auth-Method: network-trusted` headers | Without nginx, JWT validation is unavailable. The gateway grants full admin when this header is present. Production would use nginx + OAuth. |
| Python `urllib` for healthchecks | `curl` and `nc` require OS package managers (`apt`/`apk`) which are forbidden in this environment. |
| `python:3.11-slim` everywhere | Only Docker Hub official images are accessible. All dependencies installed via `pip`/`uv`. |

## Environment Constraints

This PoC runs in a **restricted environment**. The following are hard constraints embedded in every Dockerfile and script:

- **No `ghcr.io` images** — `mcp-gateway-registry` is built from source, not pulled from GitHub Container Registry
- **No OS package managers** — `apt`, `apt-get`, `yum`, `dnf`, `apk` are forbidden in all Dockerfiles
- **No `curl` or `nc`** — all healthchecks and scripts use Python `urllib` exclusively
- **Docker Hub official images only** — base image is `python:3.11-slim` across all containers

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker | >= 24 | With Compose plugin >= 2.20 |
| Git | any | For cloning the `mcp-gateway-registry` submodule |
| Python | >= 3.11 | Host only — needed for `scripts/bootstrap.sh` |
| RAM | >= 4 GB | Available for all containers |
| Network | Docker Hub + GitHub + HuggingFace Hub | See offline alternative if HuggingFace is blocked |

### Installing Docker

**macOS**
```bash
brew install --cask docker
open /Applications/Docker.app   # wait for whale icon to stabilise in menu bar
docker --version && docker compose version
```

**Linux (Ubuntu/Debian)**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
sudo systemctl enable docker && sudo systemctl start docker
docker --version && docker compose version
```

**Windows**
```
1. https://www.docker.com/products/docker-desktop
2. Download and run the installer
3. Restart when prompted
4. Open Docker Desktop after restart
5. Verify: docker --version in PowerShell
```

## Quick Start

```bash
# 1. Clone this repository
git clone <repo-url>
cd poc-mcp-discovery

# 2. Clone mcp-gateway-registry source (git — NOT a Docker image pull)
chmod +x scripts/setup-gateway-source.sh
./scripts/setup-gateway-source.sh

# 3. Copy environment config
cp .env.example .env

# 4. Download the embeddings model (~90MB, one-time)
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh

# 5. Build all images and start the stack
docker compose up -d --build

# 6. Wait for the gateway to become healthy (~120s on first start)
docker compose ps   # all containers should show "running"

# 7. Register the mock servers
chmod +x scripts/seed_gateway.sh
./scripts/seed_gateway.sh

# 8. Validate everything is working
chmod +x scripts/validate.sh
./scripts/validate.sh
```

> **First start takes longer** — the gateway loads the `all-MiniLM-L6-v2` model on startup.
> Subsequent starts are fast because the model is cached in the bind-mounted host directory.

## Verifying the Stack Manually

All commands below use Python `urllib` — no `curl` required.

### Check gateway health
```bash
python3 -c "
import urllib.request, json
r = urllib.request.urlopen('http://localhost:7860/health')
print(json.loads(r.read()))
# Expected: {'status': 'healthy', 'service': 'mcp-gateway-registry', ...}
"
```

### List registered servers
```bash
python3 -c "
import urllib.request, json
req = urllib.request.Request(
    'http://localhost:7860/api/servers',
    headers={'X-Username': 'admin', 'X-Auth-Method': 'network-trusted'},
)
r = urllib.request.urlopen(req)
data = json.loads(r.read())
servers = data if isinstance(data, list) else data.get('servers', [])
for s in servers:
    name = s.get('display_name', s.get('server_name', ''))
    tools = len(s.get('tool_list') or [])
    print(f\"{name} ({s['path']}) → {tools} tools\")
"
```

### Run a semantic search query
```bash
python3 -c "
import urllib.request, json
data = json.dumps({'query': 'create a github issue for a bug report', 'max_results': 3}).encode()
req = urllib.request.Request(
    'http://localhost:7860/api/search/semantic',
    data=data,
    headers={
        'Content-Type': 'application/json',
        'X-Username': 'admin',
        'X-Auth-Method': 'network-trusted',
    },
    method='POST'
)
body = json.loads(urllib.request.urlopen(req).read())
for t in body.get('tools', []):
    print(f\"{t['tool_name']} ({t['server_name']}) — score: {t['relevance_score']:.3f}\")
"
```

### Follow sync-worker logs
```bash
docker logs sync-worker --follow
# Look for: sync_source_fetched count=X and sync_finished errors=0
```

### Force an immediate sync (without waiting 30 min)
```bash
docker exec sync-worker python3 -c "
from config import Config
from registry_client import MCPRegistryClient
from gateway_client import GatewayClient
from syncer import run_sync
c = Config.from_env()
metrics = run_sync(MCPRegistryClient(c), GatewayClient(c), c.sync_state_file)
print(metrics)
"
```

## Running Tests

### Unit tests (no containers needed)
```bash
docker exec sync-worker pytest tests/ -v --ignore=tests/test_integration.py
```

### Integration tests (requires full stack running + seed_gateway.sh)
```bash
docker exec sync-worker pytest tests/test_integration.py -v -m integration
```

### Full suite
```bash
# Unit
docker exec sync-worker pytest tests/ -v --ignore=tests/test_integration.py

# Integration
docker exec sync-worker pytest tests/test_integration.py -v -m integration
```

Expected output (unit tests):
```
tests/test_registry_client.py .....   PASSED
tests/test_gateway_client.py  ..........  PASSED
tests/test_syncer.py          .............  PASSED
============= N passed in X.Xs =============
```

## Using with Corporate MCP Servers

To register an internal MCP server instead of the mock ones:

```bash
python3 -c "
import urllib.request, urllib.parse
server = {
    'name': 'my-internal-api',
    'description': 'Internal CRM API — search customers, create tickets, update records',
    'path': '/my-internal-api',
    'proxy_pass_url': 'http://my-internal-mcp-server:8000',
    'tags': 'internal,crm',
    'overwrite': 'true',
}
data = urllib.parse.urlencode(server).encode()
req = urllib.request.Request(
    'http://localhost:7860/api/servers/register',
    data=data,
    headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Username': 'admin',
        'X-Auth-Method': 'network-trusted',
    },
    method='POST'
)
r = urllib.request.urlopen(req)
print(r.status)
"
```

The gateway will automatically crawl `tools/list` from your server and index the tools for semantic search.

### Migrating to production

| PoC component | Production replacement |
|---|---|
| `registry.modelcontextprotocol.io` (golden source) | Internal MCP registry following the same OpenAPI spec |
| File-based storage | MongoDB or DocumentDB backend (supported by `mcp-gateway-registry`) |
| `X-Auth-Method: network-trusted` bypass | nginx reverse proxy with Keycloak/Entra ID/Okta JWT validation |
| `all-MiniLM-L6-v2` | `all-mpnet-base-v2` or API-based embeddings (OpenAI, Cohere) if recall is insufficient |
| Polling every 30 min | Event-driven webhook (on MCP Registry roadmap) |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `mcp-gateway` stays `unhealthy` | Model loading takes > 120s or FAISS init slow | Increase `start_period` in `docker-compose.yml`; check `docker logs mcp-gateway` |
| `gateway_client` returns 404 on `/api/servers` | The real API path in the cloned source differs from the spec | Inspect cloned source for actual route definitions: `grep -r "@app\.\|@router\." mcp-gateway-registry/ --include="*.py"`; update `gateway_client.py` |
| `gateway_client` returns 403 on `/api/servers/register` | `network-trusted` headers not sent | Ensure `X-Username` and `X-Auth-Method: network-trusted` are in the request |
| `sync_source_fetched count=0` in sync-worker logs | MCP Registry is unreachable | Check internet access: `docker exec sync-worker python3 -c "import urllib.request; urllib.request.urlopen('https://registry.modelcontextprotocol.io/v0/servers').read()"` |
| Mock servers show 0 tools after `seed_gateway.sh` | `seed_gateway.sh` not run or gateway unreachable | Re-run `./scripts/seed_gateway.sh`; confirm mock servers are healthy: `docker compose ps` |
| `test_does_not_update_unchanged_server` fails | State key mismatch | Ensure state file uses `io_github_test__server-a` (double `__`) — see `MCPRegistryServer.id` |
| `docker build` fails with `apt-get` error | The original `mcp-gateway-registry/Dockerfile` uses `apt` | Ensure `docker-compose.yml` points to `dockerfile: Dockerfile.gateway` (the custom one at project root), **not** the submodule's Dockerfile |
| `docker build` fails on torch install | PyTorch download slow or index URL issue | Check network; retry with `docker compose build --no-cache mcp-gateway` |
| `uv pip install` fails on `cisco-ai-a2a-scanner` | `sed` did not strip the git dep | Verify: `grep cisco-ai-a2a pyproject.toml` in the build context should return nothing |
| HuggingFace model download blocked | HuggingFace Hub is also restricted | Follow the offline model alternative below |

### Useful debug commands

```bash
# Check all container statuses and health
docker compose ps

# Follow all logs simultaneously
docker compose logs -f

# Check gateway startup output (model loading, FAISS init)
docker logs mcp-gateway

# Reset everything and start clean
docker compose down -v
docker compose up -d --build
```

### Offline model alternative (if HuggingFace Hub is blocked)

```bash
# On a machine WITH internet access:
pip install sentence-transformers
python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
m.save('/tmp/all-MiniLM-L6-v2')
"
tar czf all-MiniLM-L6-v2.tar.gz -C /tmp all-MiniLM-L6-v2

# Transfer the tar.gz to the restricted machine, then:
mkdir -p ~/mcp-gateway/models
tar xzf all-MiniLM-L6-v2.tar.gz -C ~/mcp-gateway/models/

# docker-compose.yml bind-mounts ~/mcp-gateway/models → /app/registry/models inside the container.
# The model will be at /app/registry/models/all-MiniLM-L6-v2/model.safetensors — no download needed.
```

## References

| Resource | URL |
|---|---|
| mcp-gateway-registry (source) | https://github.com/agentic-community/mcp-gateway-registry |
| Official MCP Registry | https://registry.modelcontextprotocol.io |
| MCP Registry API Reference | https://registry.modelcontextprotocol.io/docs |
| all-MiniLM-L6-v2 model | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| MCP Spec (Streamable HTTP) | https://modelcontextprotocol.io/specification/2025-03-26 |
| ADR-001 (decision record) | `ADR-001-poc-mcp-auto-discovery.md` |
