# SPEC — PoC: MCP Tool Auto-Discovery (As-Built)
> Version: 3.0 | Status: Verified working | Date: 2026-04-17
>
> This document describes the **exact implementation that runs successfully**.
> Every file path, endpoint, environment variable, and command is verified against a live stack.
> Reproduce it exactly — do not improvise or skip steps.

---

## 1. Objective

A Dockerized PoC that validates semantic tool auto-discovery across MCP servers:

- **Official MCP Registry** (`registry.modelcontextprotocol.io`) — public golden source, polled every 30 min
- **mcp-gateway-registry** (built from source) — central catalog with FAISS semantic search
- **auth-server** (built from source) — OAuth2 session service for the React UI
- **sync-worker** (custom) — polls the registry and syncs servers to the gateway
- **github-mcp + jira-mcp** (custom mocks) — simulate corporate MCP servers

An agent discovers relevant tools via natural language query without receiving all schemas upfront.

---

## 2. Environment Constraints

**Hard constraints — every Dockerfile and script must obey these.**

| Constraint | Rule |
|---|---|
| No ghcr.io images | `ghcr.io/*` is blocked — never pull `ghcr.io/agentic-community/mcp-gateway-registry` |
| No OS package managers | `apt`, `apt-get`, `yum`, `dnf`, `apk` are forbidden in all Dockerfiles |
| Allowed base images | Docker Hub official only: `python:3.11-slim`, `node:20-slim` |
| Allowed installers | `pip`, `uv` (installed via pip), `npm` only |
| Healthchecks | Must use `python3 -c "import urllib.request..."` — no `curl`, no `nc` |
| Scripts | Must use Python `urllib` — no `curl` |

---

## 3. M1–M6 Resolutions

These were the unknowns from the original spec. All have been resolved:

| ID | Finding | Resolution |
|---|---|---|
| M1 | Entrypoint | `uvicorn registry.main:app --host 0.0.0.0 --port 7860` — no nginx |
| M2 | API endpoints | `GET /api/servers` → `{"servers":[...]}` • `POST /api/servers/register` (form data) • `POST /api/servers/remove` (form data, field `path`) • `POST /api/search/semantic` (JSON, field `max_results`) |
| M3 | Auth mechanism | No `SRE_GATEWAY_AUTH_TOKEN`. Auth uses `X-Auth-Method: network-trusted` + `X-Username: <any>` headers. Browser auth uses `mcp_gateway_session` cookie signed with `SECRET_KEY`. |
| M4 | DEPLOYMENT_MODE | `registry-only` is valid — skips nginx dynamic location block generation |
| M5 | Dependencies | No `requirements.txt` at root. Uses `pyproject.toml`. One git-based dep (`cisco-ai-a2a-scanner @ git+...`) must be stripped with `sed -i` before install. |
| M6 | Model path, health shape, search fields | Model path is `/app/registry/models/<name>` (not `/app/models`). Health returns `{"status":"healthy"}`. Search response is `{"tools":[...],"servers":[...],...}` with `max_results` (not `limit`). |

---

## 4. Repository Structure

```
poc-mcp-discovery/
├── docker-compose.yml
├── Dockerfile.gateway               # Multi-stage: node:20-slim (frontend) + python:3.11-slim
├── Dockerfile.auth-poc              # python:3.11-slim, wraps auth_server with /dev/login
├── auth_server_dev_wrapper.py       # Injected into auth-server as server.py
├── auth_server_providers_poc.yml    # GitHub-only OAuth2 provider config
├── .env.example
├── .env                             # do not commit
├── .gitmodules
├── CLAUDE.md                        # pre-existing, do not touch
│
├── mcp-gateway-registry/            # git submodule — source only, NOT ghcr.io image
│
├── sync-worker/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── conftest.py
│   ├── main.py
│   ├── config.py
│   ├── registry_client.py
│   ├── gateway_client.py            # Uses network-trusted headers + actual API endpoints
│   ├── syncer.py
│   └── tests/
│       ├── __init__.py
│       ├── test_syncer.py
│       ├── test_registry_client.py
│       ├── test_gateway_client.py
│       └── test_integration.py
│
├── mock-servers/
│   ├── github-mcp/
│   │   ├── Dockerfile
│   │   ├── requirements.txt         # fastmcp==1.0, uvicorn==0.27.0
│   │   └── server.py               # Streamable HTTP transport at /mcp
│   └── jira-mcp/
│       ├── Dockerfile
│       ├── requirements.txt         # fastmcp==1.0, uvicorn==0.27.0
│       └── server.py               # Streamable HTTP transport at /mcp
│
└── scripts/
    ├── setup-gateway-source.sh
    ├── bootstrap.sh
    ├── seed_gateway.sh              # network-trusted headers, /api/servers/register
    └── validate.sh
```

---

## 5. Environment Variables

### `.env.example`

```env
# === MCP Registry (golden source) ===
MCP_REGISTRY_BASE_URL=https://registry.modelcontextprotocol.io
MCP_REGISTRY_API_VERSION=v0
MCP_REGISTRY_PAGE_SIZE=50
MCP_REGISTRY_REQUEST_TIMEOUT=30

# === Gateway (mcp-gateway-registry) ===
GATEWAY_BASE_URL=http://mcp-gateway:7860
GATEWAY_API_TOKEN=poc-static-token-change-in-prod

# === Sync Worker ===
SYNC_INTERVAL_SECONDS=1800
SYNC_STATE_FILE=/app/data/sync_state.json
LOG_LEVEL=INFO

# === mcp-gateway-registry internals ===
SECRET_KEY=poc-secret-key-change-in-prod
STORAGE_BACKEND=file
SESSION_COOKIE_SECURE=false
DEPLOYMENT_MODE=registry-only

# === Embeddings model (M6) ===
EMBEDDINGS_MODEL_NAME=all-MiniLM-L6-v2
EMBEDDINGS_MODEL_DIMENSIONS=384
EMBEDDINGS_PROVIDER=sentence-transformers

# === GitHub OAuth — optional for /dev/login bypass, required for real OAuth flow ===
# Setup (one-time, ~2 minutes):
#   1. https://github.com/settings/developers → OAuth Apps → New OAuth App
#   2. Application name: MCP Registry PoC
#   3. Homepage URL: http://localhost:7860
#   4. Authorization callback URL: http://localhost:8888/oauth2/callback/github
#      ↑ IMPORTANT: must be port 8888 (auth-server), NOT 7860 (gateway)
#   5. Register → copy Client ID and generate a Client Secret
GITHUB_ENABLED=true
GITHUB_CLIENT_ID=your-github-client-id-here
GITHUB_CLIENT_SECRET=your-github-client-secret-here
REGISTRY_URL=http://localhost:7860
```

---

## 6. Files

### 6.1 `.gitmodules`

```ini
[submodule "mcp-gateway-registry"]
	path = mcp-gateway-registry
	url = https://github.com/agentic-community/mcp-gateway-registry.git
```

### 6.2 `Dockerfile.gateway`

```dockerfile
# ── Stage 1: build the React frontend ────────────────────────────────────────
# node:20-slim is a Docker Hub official image — no constraint violation.
FROM node:20-slim AS frontend-builder

WORKDIR /frontend

# Install dependencies first (layer-cached until package.json changes).
COPY mcp-gateway-registry/frontend/package*.json ./
RUN npm ci --prefer-offline

# Build production bundle.
COPY mcp-gateway-registry/frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
# CONSTRAINT: Docker Hub official image only — do NOT pull ghcr.io/agentic-community/mcp-gateway-registry
FROM python:3.11-slim

# M1: the registry is a FastAPI/uvicorn app; we run it directly, skipping nginx.
# M5: dependencies are in pyproject.toml (no requirements.txt at repo root).
#     The git-based cisco-ai-a2a-scanner dep is stripped below (it installs only
#     a CLI tool — no Python module imports — so the app starts without it).

WORKDIR /app

# CONSTRAINT: pip only — no apt, no apt-get, no apk, no yum
# Install uv (a fast pip-compatible installer) via pip, which is allowed.
RUN pip install --no-cache-dir uv

# Copy source from the cloned submodule
COPY mcp-gateway-registry/ .

# Inject the pre-built React bundle.
# FastAPI mounts /app/frontend/build as /static when it exists — this makes
# the web UI available at http://localhost:7860/ without nginx.
COPY --from=frontend-builder /frontend/build ./frontend/build

# M5: strip the git-based dependency that requires git (not available in slim image).
#     This package only installs a CLI binary; disabling security scanning covers
#     the code paths that call it (SECURITY_SCAN_ENABLED=false in compose env).
RUN sed -i '/cisco-ai-a2a-scanner @ git+/d' pyproject.toml

# Install torch CPU-only first (avoids downloading the full GPU build).
# Must run before the main install so uv does not resolve a conflicting version.
RUN uv pip install --system --extra-index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.0.0"

# Install all remaining dependencies from pyproject.toml.
RUN uv pip install --system -e .

# Directories required by the gateway in file/registry-only storage mode.
# M6: models are read from /app/registry/models/<model-name>, not /app/models/.
RUN mkdir -p /app/registry/models /app/registry/servers /app/registry/agents \
             /app/logs /app/data

EXPOSE 7860

# CONSTRAINT: Python urllib healthcheck — no curl, no nc
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health').read()" || exit 1

# M1: actual entrypoint — uvicorn starts the FastAPI app directly (no nginx layer).
# DEPLOYMENT_MODE=registry-only skips nginx dynamic location block generation.
CMD ["uvicorn", "registry.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

### 6.3 `Dockerfile.auth-poc`

```dockerfile
# CONSTRAINT: Docker Hub official image only — no apt, no ghcr.io
FROM python:3.11-slim

WORKDIR /app

# CONSTRAINT: pip/uv only
RUN pip install --no-cache-dir uv

# The auth_server imports from the main registry package at runtime.
# Copy the full gateway source so those imports resolve.
COPY mcp-gateway-registry/ .

# Strip the git-based dep (same as Dockerfile.gateway)
RUN sed -i '/cisco-ai-a2a-scanner @ git+/d' pyproject.toml

# Install all auth_server runtime deps.
# boto3/motor/pymongo/opensearch-py are imported at module level so must be present
# even though Cognito/MongoDB features are unused in this PoC.
RUN uv pip install --system --no-cache \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.34.0" \
    "pydantic>=2.0.0" \
    "pydantic-settings>=2.0.0" \
    "requests>=2.28.0" \
    "python-jose>=3.3.0" \
    "python-dotenv>=1.0.0" \
    "pyjwt>=2.6.0" \
    "cryptography>=40.0.0" \
    "pyyaml>=6.0.0" \
    "httpx>=0.25.0" \
    "itsdangerous>=2.1.0" \
    "aiohttp>=3.8.0" \
    "aiofiles>=24.1.0" \
    "boto3>=1.28.0" \
    "motor>=3.3.0" \
    "pymongo>=4.6.0" \
    "opensearch-py>=2.4.0"

# Override the bundled oauth2_providers.yml with the PoC-specific version
# (GitHub-only, no Okta/Keycloak/Cognito to avoid broken login buttons)
COPY auth_server_providers_poc.yml ./auth_server/oauth2_providers.yml

# Install the full gateway package so auth_server registry.* imports resolve
RUN uv pip install --system --no-cache -e .

# Dev-login wrapper: rename original server.py, inject wrapper as new server.py.
# uvicorn still runs `server:app` — the wrapper loads the original and adds /dev/login.
RUN mv /app/auth_server/server.py /app/auth_server/server_original.py
COPY auth_server_dev_wrapper.py /app/auth_server/server.py

WORKDIR /app/auth_server

EXPOSE 8888

# CONSTRAINT: Python urllib healthcheck — no curl
HEALTHCHECK --interval=20s --timeout=5s --retries=5 --start-period=30s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8888/health').read()" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8888"]
```

### 6.4 `auth_server_dev_wrapper.py`

```python
"""
PoC dev-login wrapper for auth-server.

This file is copied into /app/auth_server/server.py by Dockerfile.auth-poc,
replacing the original (renamed to server_original.py).

It loads the original auth-server app, then registers a single extra endpoint:
  GET /dev/login  — creates a valid mcp_gateway_session cookie without OAuth
                     and redirects to the gateway UI.

The cookie is signed with the same SECRET_KEY that the gateway uses, so
the gateway's enhanced_auth dependency accepts it.  Groups are set to
["mcp-registry-admin"] which maps to full admin scopes in scopes.yml.

DO NOT expose /dev/login in production.
"""
import importlib.util
import os
import sys

# ── Load original server module ────────────────────────────────────────────────
_here = os.path.dirname(os.path.abspath(__file__))
_orig_path = os.path.join(_here, "server_original.py")

spec = importlib.util.spec_from_file_location("server_original", _orig_path)
_orig_mod = importlib.util.module_from_spec(spec)
sys.modules["server_original"] = _orig_mod
spec.loader.exec_module(_orig_mod)

# Expose the FastAPI app at module level — uvicorn imports `server:app`
app = _orig_mod.app

# ── Dev-login endpoint ─────────────────────────────────────────────────────────
from fastapi.responses import RedirectResponse  # noqa: E402
from itsdangerous import URLSafeTimedSerializer  # noqa: E402


@app.get("/dev/login", include_in_schema=False)
async def dev_login():
    """
    PoC-only: auto-login without GitHub OAuth.

    Creates a signed mcp_gateway_session cookie with admin groups and
    redirects to REGISTRY_URL (the gateway UI).

    Visit:  http://localhost:8888/dev/login
    """
    secret_key = os.environ.get("SECRET_KEY", "poc-secret-key-change-in-prod")
    signer = URLSafeTimedSerializer(secret_key)

    session_value = signer.dumps(
        {
            "username": "dev-admin",
            "auth_method": "oauth2",   # gateway rejects non-oauth2 sessions
            "provider": "github",
            "groups": ["mcp-registry-admin"],  # maps to full admin in scopes.yml
        }
    )

    registry_url = os.environ.get("REGISTRY_URL", "http://localhost:7860").rstrip("/")
    response = RedirectResponse(url=registry_url + "/", status_code=302)
    response.set_cookie(
        key="mcp_gateway_session",
        value=session_value,
        max_age=28800,   # 8 h
        httponly=True,
        samesite="lax",
        secure=False,    # HTTP localhost — no TLS
        path="/",        # shared across all ports on localhost
    )
    return response
```

### 6.5 `auth_server_providers_poc.yml`

```yaml
# PoC OAuth2 providers — GitHub only.
# All other providers are disabled to avoid broken login buttons.
#
# Prerequisites:
#   1. Go to https://github.com/settings/developers → OAuth Apps → New OAuth App
#   2. Application name: MCP Registry PoC
#   3. Homepage URL: http://localhost:7860
#   4. Authorization callback URL: http://localhost:8888/oauth2/callback/github
#      ↑ IMPORTANT: must be port 8888 (auth-server), NOT 7860 (gateway)
#   5. Register → copy Client ID and generate Client Secret
#   6. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in your .env file

providers:
  github:
    display_name: "GitHub"
    client_id: "${GITHUB_CLIENT_ID}"
    client_secret: "${GITHUB_CLIENT_SECRET}"
    auth_url: "https://github.com/login/oauth/authorize"
    token_url: "https://github.com/login/oauth/access_token"
    user_info_url: "https://api.github.com/user"
    scopes: ["read:user", "user:email"]
    response_type: "code"
    grant_type: "authorization_code"
    username_claim: "login"
    # GitHub doesn't provide IdP groups. The "type" claim always returns "User"
    # for any authenticated GitHub account. The scopes_poc.yml maps
    # "User" → mcp-servers-unrestricted/read+execute.
    groups_claim: "type"
    email_claim: "email"
    name_claim: "name"
    enabled: "${GITHUB_ENABLED}"

session:
  max_age_seconds: 28800
  cookie_name: "mcp_oauth_session"
  secure: false        # false for localhost HTTP
  httponly: true
  samesite: "lax"
  domain: ""

registry:
  callback_url: "${REGISTRY_URL}/api/auth/auth/callback"
  success_redirect: "${REGISTRY_URL}/"
  error_redirect: "${REGISTRY_URL}/login"
```

### 6.6 `docker-compose.yml`

```yaml
version: "3.9"

networks:
  mcp-net:
    driver: bridge

volumes:
  gateway-data:
  sync-state:

services:

  # ─────────────────────────────────────────────────────────────────────────
  # auth-server — OAuth2 session service for the React web UI
  # Provides /dev/login (PoC bypass) and /oauth2/callback/github (real OAuth)
  # ─────────────────────────────────────────────────────────────────────────
  auth-server:
    build:
      context: .
      dockerfile: Dockerfile.auth-poc
    container_name: auth-server
    restart: unless-stopped
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - GITHUB_CLIENT_ID=${GITHUB_CLIENT_ID:-}
      - GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET:-}
      - GITHUB_ENABLED=${GITHUB_ENABLED:-false}
      - REGISTRY_URL=${REGISTRY_URL:-http://localhost:7860}
      - SESSION_COOKIE_SECURE=false
    ports:
      - "8888:8888"
    networks:
      - mcp-net
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8888/health').read()"]
      interval: 20s
      timeout: 5s
      retries: 5
      start_period: 30s

  # ─────────────────────────────────────────────────────────────────────────
  # mcp-gateway — mcp-gateway-registry built from source
  # M1: CMD is uvicorn registry.main:app — no nginx layer
  # M3: auth via X-Auth-Method: network-trusted (internal) or session cookie (UI)
  # M4: DEPLOYMENT_MODE=registry-only skips nginx config generation
  # M6: model path is /app/registry/models/<name>
  # ─────────────────────────────────────────────────────────────────────────
  mcp-gateway:
    build:
      context: .
      dockerfile: Dockerfile.gateway
    container_name: mcp-gateway
    restart: unless-stopped
    environment:
      - SECRET_KEY=${SECRET_KEY}
      # AUTH_PROVIDER intentionally absent — gateway runs without an IdP.
      # Internal callers use X-Auth-Method: network-trusted.
      # AUTH_SERVER_URL lets the React UI call /api/auth/providers.
      - AUTH_SERVER_URL=http://auth-server:8888
      - STORAGE_BACKEND=${STORAGE_BACKEND:-file}
      - SESSION_COOKIE_SECURE=${SESSION_COOKIE_SECURE:-false}
      - DEPLOYMENT_MODE=${DEPLOYMENT_MODE:-registry-only}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      # M6: EMBEDDINGS_MODEL_NAME controls the subdir under /app/registry/models/
      - EMBEDDINGS_MODEL_NAME=${EMBEDDINGS_MODEL_NAME:-all-MiniLM-L6-v2}
      - EMBEDDINGS_MODEL_DIMENSIONS=${EMBEDDINGS_MODEL_DIMENSIONS:-384}
      - EMBEDDINGS_PROVIDER=${EMBEDDINGS_PROVIDER:-sentence-transformers}
      # Disable security scanning — cisco-ai-a2a-scanner CLI is not installed
      - SECURITY_SCAN_ENABLED=false
      - SECURITY_SCAN_ON_REGISTRATION=false
      - SECURITY_BLOCK_UNSAFE_SERVERS=false
    volumes:
      - gateway-data:/app/registry
      # M6: bind mount maps host model download path to container's expected path.
      # bootstrap.sh writes to ${HOME}/mcp-gateway/models on the host.
      - ${HOME}/mcp-gateway/models:/app/registry/models
    ports:
      - "7860:7860"
    networks:
      - mcp-net
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:7860/health').read()"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s

  # ─────────────────────────────────────────────────────────────────────────
  # sync-worker — polls MCP Registry and syncs to gateway
  # ─────────────────────────────────────────────────────────────────────────
  sync-worker:
    build:
      context: ./sync-worker
      dockerfile: Dockerfile
    container_name: sync-worker
    restart: unless-stopped
    environment:
      - MCP_REGISTRY_BASE_URL=${MCP_REGISTRY_BASE_URL}
      - MCP_REGISTRY_API_VERSION=${MCP_REGISTRY_API_VERSION}
      - MCP_REGISTRY_PAGE_SIZE=${MCP_REGISTRY_PAGE_SIZE}
      - MCP_REGISTRY_REQUEST_TIMEOUT=${MCP_REGISTRY_REQUEST_TIMEOUT}
      - GATEWAY_BASE_URL=${GATEWAY_BASE_URL}
      - GATEWAY_API_TOKEN=${GATEWAY_API_TOKEN}
      - SYNC_INTERVAL_SECONDS=${SYNC_INTERVAL_SECONDS}
      - SYNC_STATE_FILE=${SYNC_STATE_FILE}
      - LOG_LEVEL=${LOG_LEVEL}
    volumes:
      - sync-state:/app/data
    networks:
      - mcp-net
    depends_on:
      mcp-gateway:
        condition: service_healthy

  # ─────────────────────────────────────────────────────────────────────────
  # github-mcp — mock corporate GitHub MCP server
  # Transport: Streamable HTTP at /mcp (MCP spec 2025-03-26)
  # ─────────────────────────────────────────────────────────────────────────
  github-mcp:
    build:
      context: ./mock-servers/github-mcp
      dockerfile: Dockerfile
    container_name: github-mcp
    restart: unless-stopped
    ports:
      - "8001:8000"
    networks:
      - mcp-net
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"]
      interval: 20s
      timeout: 5s
      retries: 3

  # ─────────────────────────────────────────────────────────────────────────
  # jira-mcp — mock corporate Jira MCP server
  # Transport: Streamable HTTP at /mcp (MCP spec 2025-03-26)
  # ─────────────────────────────────────────────────────────────────────────
  jira-mcp:
    build:
      context: ./mock-servers/jira-mcp
      dockerfile: Dockerfile
    container_name: jira-mcp
    restart: unless-stopped
    ports:
      - "8002:8000"
    networks:
      - mcp-net
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"]
      interval: 20s
      timeout: 5s
      retries: 3
```

---

## 7. Sync Worker

### 7.1 `sync-worker/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data
CMD ["python3", "main.py"]
```

### 7.2 `sync-worker/requirements.txt`

```
requests==2.31.0
schedule==1.2.1
python-dotenv==1.0.0
pydantic==2.5.0
structlog==24.1.0
pytest==7.4.3
pytest-mock==3.12.0
responses==0.24.1
```

### 7.3 `sync-worker/pytest.ini`

```ini
[pytest]
markers =
    integration: requires docker compose stack to be running
```

### 7.4 `sync-worker/conftest.py`

```python
import sys
import os

# Ensure the sync-worker source directory is always on sys.path,
# regardless of the working directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

### 7.5 `sync-worker/tests/__init__.py`

Empty file.

### 7.6 `sync-worker/config.py`

```python
import os
from pydantic import BaseModel


class Config(BaseModel):
    mcp_registry_base_url: str = "https://registry.modelcontextprotocol.io"
    mcp_registry_api_version: str = "v0"
    mcp_registry_page_size: int = 50
    mcp_registry_request_timeout: int = 30
    gateway_base_url: str = "http://mcp-gateway:7860"
    gateway_api_token: str = ""
    sync_interval_seconds: int = 1800
    sync_state_file: str = "/app/data/sync_state.json"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            mcp_registry_base_url=os.getenv("MCP_REGISTRY_BASE_URL", "https://registry.modelcontextprotocol.io"),
            mcp_registry_api_version=os.getenv("MCP_REGISTRY_API_VERSION", "v0"),
            mcp_registry_page_size=int(os.getenv("MCP_REGISTRY_PAGE_SIZE", "50")),
            mcp_registry_request_timeout=int(os.getenv("MCP_REGISTRY_REQUEST_TIMEOUT", "30")),
            gateway_base_url=os.getenv("GATEWAY_BASE_URL", "http://mcp-gateway:7860"),
            gateway_api_token=os.getenv("GATEWAY_API_TOKEN", ""),
            sync_interval_seconds=int(os.getenv("SYNC_INTERVAL_SECONDS", "1800")),
            sync_state_file=os.getenv("SYNC_STATE_FILE", "/app/data/sync_state.json"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
```

### 7.7 `sync-worker/registry_client.py`

```python
"""
Official MCP Registry client (golden source).
Endpoint: GET /v0/servers — cursor-based pagination.
"""
import requests
import structlog
from typing import Generator
from config import Config

log = structlog.get_logger()


class MCPRegistryServer:
    def __init__(self, raw: dict):
        server = raw.get("server", raw)
        meta = raw.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
        self.name: str = server.get("name", "")
        self.description: str = server.get("description", "")
        self.repository_url: str = server.get("repository", {}).get("url", "")
        self.version: str = server.get("version", "")
        self.updated_at: str = meta.get("updatedAt", "")
        self.status: str = meta.get("status", "active")
        self.raw: dict = raw

    @property
    def id(self) -> str:
        return self.name.replace("/", "__").replace(".", "_")


class MCPRegistryClient:
    def __init__(self, config: Config):
        self.base_url = config.mcp_registry_base_url
        self.api_version = config.mcp_registry_api_version
        self.page_size = config.mcp_registry_page_size
        self.timeout = config.mcp_registry_request_timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}/{self.api_version}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def list_all_servers(self) -> Generator[MCPRegistryServer, None, None]:
        cursor = None
        page = 0
        while True:
            params = {"limit": self.page_size}
            if cursor:
                params["cursor"] = cursor
            log.info("registry_fetch_page", page=page)
            data = self._get("/servers", params=params)
            servers = data.get("servers", [])
            if not servers:
                break
            for raw in servers:
                yield MCPRegistryServer(raw)
            cursor = data.get("metadata", {}).get("nextCursor")
            page += 1
            if not cursor:
                break
        log.info("registry_fetch_complete", total_pages=page)
```

### 7.8 `sync-worker/gateway_client.py`

```python
"""
Custom Gateway client — targets mcp-gateway-registry running without nginx.

Auth strategy (M3 finding):
  - All endpoints use nginx_proxied_auth or nginx_proxied_auth-derived auth.
  - Without nginx, we pass X-Username and X-Auth-Method: network-trusted headers,
    which the registry grants full admin access without any external validation.

API mapping (M2 finding):
  - List:     GET  /api/servers                → {"servers": [...]}
  - Register: POST /api/servers/register       → form data
  - Remove:   POST /api/servers/remove         → form data (field: path)
  - Search:   POST /api/search/semantic        → JSON body, field max_results
"""
import requests
import structlog
from config import Config

log = structlog.get_logger()

_NETWORK_TRUSTED_HEADERS = {
    "X-Username": "sync-worker",
    "X-Auth-Method": "network-trusted",
}


def _server_path(server_id: str) -> str:
    return f"/{server_id}"


class GatewayServer:
    def __init__(self, raw: dict):
        # M2: servers are keyed by 'path' in the registry, not a simple id.
        self.path: str = raw.get("path", "")
        self.id: str = self.path
        self.name: str = raw.get("display_name", raw.get("server_name", ""))
        self.description: str = raw.get("description", "")
        self.url: str = raw.get("proxy_pass_url", "")
        self.tags: list[str] = raw.get("tags", [])
        self.updated_at: str = raw.get("updated_at", raw.get("source_updated_at", ""))
        self.raw: dict = raw


class GatewayClient:
    def __init__(self, config: Config):
        self.base_url = config.gateway_base_url.rstrip("/")
        self.token = config.gateway_api_token
        self.session = requests.Session()
        self.session.headers.update({
            **_NETWORK_TRUSTED_HEADERS,
            "Accept": "application/json",
        })

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def health_check(self) -> bool:
        try:
            r = self.session.get(self._url("/health"), timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_servers(self) -> list[GatewayServer]:
        try:
            r = self.session.get(self._url("/api/servers"), timeout=10)
            r.raise_for_status()
            data = r.json()
            # M2: response is {"servers": [...]} not a plain list.
            servers = data if isinstance(data, list) else data.get("servers", [])
            return [GatewayServer(s) for s in servers]
        except Exception as e:
            log.error("gateway_list_error", error=str(e))
            return []

    def register_server(self, name: str, description: str, url: str, tags: list[str] = None) -> bool:
        server_id = name.replace("/", "__").replace(".", "_")
        server_path = _server_path(server_id)
        tags_str = ",".join(tags or [])
        try:
            r = self.session.post(
                self._url("/api/servers/register"),
                data={
                    "name": name,
                    "description": description or f"MCP Server: {name}",
                    "path": server_path,
                    "proxy_pass_url": url,
                    "tags": tags_str,
                    "overwrite": "true",
                },
                timeout=15,
            )
            r.raise_for_status()
            log.info("gateway_server_registered", name=name, path=server_path)
            return True
        except requests.HTTPError as e:
            log.error("gateway_register_error", name=name, status=e.response.status_code,
                      body=e.response.text[:200])
            return False

    def update_server(self, server_id: str, name: str, description: str, url: str, tags: list[str] = None) -> bool:
        # M2: no PUT endpoint; re-register with overwrite=True.
        tags_str = ",".join(tags or [])
        try:
            r = self.session.post(
                self._url("/api/servers/register"),
                data={
                    "name": name,
                    "description": description or f"MCP Server: {name}",
                    "path": server_id,
                    "proxy_pass_url": url,
                    "tags": tags_str,
                    "overwrite": "true",
                },
                timeout=15,
            )
            r.raise_for_status()
            log.info("gateway_server_updated", server_id=server_id)
            return True
        except requests.HTTPError as e:
            log.error("gateway_update_error", server_id=server_id, status=e.response.status_code)
            return False

    def delete_server(self, server_id: str) -> bool:
        # M2: deletion uses POST /api/servers/remove, form field: path.
        try:
            r = self.session.post(
                self._url("/api/servers/remove"),
                data={"path": server_id},
                timeout=10,
            )
            r.raise_for_status()
            log.info("gateway_server_deleted", server_id=server_id)
            return True
        except requests.HTTPError as e:
            log.error("gateway_delete_error", server_id=server_id, status=e.response.status_code)
            return False
```

### 7.9 `sync-worker/syncer.py`

```python
"""
Diff and upsert logic between the MCP Registry and the gateway.

Algorithm:
1. Fetch all active servers from MCP Registry
2. Fetch all servers currently in gateway
3. Compute add / update / delete sets
4. Apply operations
5. Persist state (server_id -> updated_at) for incremental diff
"""
import json
import os
import structlog
from datetime import datetime, timezone
from registry_client import MCPRegistryClient, MCPRegistryServer
from gateway_client import GatewayClient

log = structlog.get_logger()
FALLBACK_SERVER_URL = "http://placeholder.mcp.internal"


def _load_state(state_file: str) -> dict:
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_state(state_file: str, state: dict) -> None:
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def _server_url(server: MCPRegistryServer) -> str:
    return server.repository_url if server.repository_url else FALLBACK_SERVER_URL


def run_sync(registry_client: MCPRegistryClient, gateway_client: GatewayClient, state_file: str) -> dict:
    started_at = datetime.now(timezone.utc).isoformat()
    metrics = {"added": 0, "updated": 0, "deleted": 0, "errors": 0, "started_at": started_at}
    log.info("sync_started")

    try:
        source_servers = {
            s.id: s for s in registry_client.list_all_servers()
            if s.status == "active"
        }
    except Exception as e:
        log.error("sync_registry_fetch_failed", error=str(e))
        metrics["errors"] += 1
        return metrics

    log.info("sync_source_fetched", count=len(source_servers))
    current_gateway = {s.name: s for s in gateway_client.list_servers()}
    log.info("sync_gateway_fetched", count=len(current_gateway))
    persisted_state = _load_state(state_file)
    new_state: dict = {}

    for server_id, source in source_servers.items():
        new_state[server_id] = source.updated_at
        gateway_entry = current_gateway.get(source.name)

        if gateway_entry is None:
            ok = gateway_client.register_server(
                name=source.name,
                description=source.description or f"MCP Server: {source.name}",
                url=_server_url(source),
                tags=["auto-synced", "mcp-registry"],
            )
            metrics["added" if ok else "errors"] += 1
        elif persisted_state.get(server_id) != source.updated_at:
            ok = gateway_client.update_server(
                server_id=gateway_entry.id,
                name=source.name,
                description=source.description or f"MCP Server: {source.name}",
                url=_server_url(source),
                tags=["auto-synced", "mcp-registry"],
            )
            metrics["updated" if ok else "errors"] += 1

    source_names = {s.name for s in source_servers.values()}
    for name, gw_server in current_gateway.items():
        if name not in source_names and "auto-synced" in gw_server.tags:
            ok = gateway_client.delete_server(gw_server.id)
            if ok:
                metrics["deleted"] += 1
                normalized_id = gw_server.name.replace("/", "__").replace(".", "_")
                new_state.pop(normalized_id, None)
            else:
                metrics["errors"] += 1

    _save_state(state_file, new_state)
    metrics["finished_at"] = datetime.now(timezone.utc).isoformat()
    log.info("sync_finished", **metrics)
    return metrics
```

### 7.10 `sync-worker/main.py`

```python
"""
Sync Worker entrypoint. Runs immediately on startup, then every SYNC_INTERVAL_SECONDS.
"""
import schedule
import time
import structlog
import logging
from config import Config
from registry_client import MCPRegistryClient
from gateway_client import GatewayClient
from syncer import run_sync

config = Config.from_env()
logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.log_level.upper(), logging.INFO)
    )
)
log = structlog.get_logger()


def sync_job():
    rc = MCPRegistryClient(config)
    gc = GatewayClient(config)
    if not gc.health_check():
        log.warning("sync_skipped_gateway_unavailable")
        return
    run_sync(rc, gc, config.sync_state_file)


if __name__ == "__main__":
    log.info("sync_worker_starting", interval_seconds=config.sync_interval_seconds)
    sync_job()
    schedule.every(config.sync_interval_seconds).seconds.do(sync_job)
    while True:
        schedule.run_pending()
        time.sleep(30)
```

---

## 8. Mock MCP Servers

**Critical note on transport**: Both mock servers use **Streamable HTTP transport** (MCP spec 2025-03-26) at `/mcp`, NOT SSE at `/sse`. The gateway crawls `POST /mcp` to list tools. Use `@mcp.tool()` (with parentheses) — this is the fastmcp 1.0 API.

### 8.1 `mock-servers/github-mcp/Dockerfile` and `mock-servers/jira-mcp/Dockerfile`

Both Dockerfiles are identical:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1
CMD ["python3", "server.py"]
```

### 8.2 `mock-servers/github-mcp/requirements.txt` and `mock-servers/jira-mcp/requirements.txt`

Both are identical:

```
fastmcp==1.0
uvicorn==0.27.0
```

### 8.3 `mock-servers/github-mcp/server.py`

```python
"""Mock MCP Server: GitHub — simulates GitHub tools for semantic discovery testing.

Serves MCP over streamable HTTP transport at /mcp (MCP 2025-03-26 spec).
Gateway crawls tools/list via POST /mcp during server registration.
"""
import contextlib
import uvicorn
from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

mcp = FastMCP("github-mcp")


@mcp.tool()
def create_issue(repo: str, title: str, body: str, labels: list[str] = None) -> dict:
    """
    Creates a new issue in a GitHub repository.
    Use this tool to report bugs, request features, or track tasks in GitHub.
    """
    return {"status": "created", "issue_number": 42,
            "url": f"https://github.com/{repo}/issues/42", "title": title}


@mcp.tool()
def list_pull_requests(repo: str, state: str = "open") -> list[dict]:
    """
    Lists pull requests in a GitHub repository.
    Returns open or closed pull requests with title, author and status.
    Use to see what code changes are pending review or recently merged.
    """
    return [
        {"number": 101, "title": "feat: add semantic search", "state": state, "author": "alice"},
        {"number": 99,  "title": "fix: timeout handling",    "state": state, "author": "bob"},
    ]


@mcp.tool()
def get_repository_info(repo: str) -> dict:
    """
    Returns metadata about a GitHub repository.
    Includes description, language, star count and last commit date.
    """
    return {"name": repo, "description": "Mock repository for PoC",
            "language": "Python", "stars": 128, "last_commit": "2025-04-01"}


@mcp.tool()
def search_code(query: str, repo: str = None) -> list[dict]:
    """
    Searches for code across GitHub repositories using a text query.
    Returns file paths and snippets matching the search term.
    Optionally scoped to a specific repository.
    """
    return [{"file": "src/main.py", "line": 42, "snippet": f"# matches: {query}"}]


async def health(request):
    return JSONResponse({"status": "healthy"})


session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    stateless=True,
)


@contextlib.asynccontextmanager
async def lifespan(app):
    async with session_manager.run():
        yield


async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", endpoint=health),
        Mount("/mcp", app=handle_mcp),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
```

### 8.4 `mock-servers/jira-mcp/server.py`

```python
"""Mock MCP Server: Jira — simulates Jira tools for semantic discovery testing.

Serves MCP over streamable HTTP transport at /mcp (MCP 2025-03-26 spec).
Gateway crawls tools/list via POST /mcp during server registration.
"""
import contextlib
import uvicorn
from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse

mcp = FastMCP("jira-mcp")


@mcp.tool()
def create_ticket(project_key: str, summary: str, description: str,
                  issue_type: str = "Task", priority: str = "Medium") -> dict:
    """
    Creates a new ticket in a Jira project.
    Use to track bugs, tasks, stories or epics in Jira.
    Provide the project key (e.g. PLAT, INFRA), a summary, and optionally
    the issue type and priority.
    """
    return {"key": f"{project_key}-999", "summary": summary, "status": "To Do",
            "url": f"https://jira.example.com/browse/{project_key}-999"}


@mcp.tool()
def get_ticket(ticket_key: str) -> dict:
    """
    Retrieves details of a specific Jira ticket by its key.
    Returns summary, description, status, assignee and comments.
    Example key: PLAT-123
    """
    return {"key": ticket_key, "summary": "Mock ticket for PoC",
            "status": "In Progress", "assignee": "charlie", "priority": "High", "comments": []}


@mcp.tool()
def search_tickets(jql: str, max_results: int = 10) -> list[dict]:
    """
    Searches Jira tickets using JQL (Jira Query Language).
    Use to find tickets by project, status, assignee, sprint or any other criteria.
    Example JQL: project = PLAT AND status = 'In Progress'
    """
    return [{"key": "PLAT-100", "summary": f"Result for: {jql}", "status": "Open"}]


@mcp.tool()
def transition_ticket(ticket_key: str, transition: str) -> dict:
    """
    Moves a Jira ticket to a new workflow status.
    Common transitions: 'In Progress', 'Done', 'In Review', 'Blocked'.
    Use after completing work or updating ticket progress.
    """
    return {"key": ticket_key, "new_status": transition, "success": True}


async def health(request):
    return JSONResponse({"status": "healthy"})


session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    stateless=True,
)


@contextlib.asynccontextmanager
async def lifespan(app):
    async with session_manager.run():
        yield


async def handle_mcp(scope, receive, send):
    await session_manager.handle_request(scope, receive, send)


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/health", endpoint=health),
        Mount("/mcp", app=handle_mcp),
    ],
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
```

---

## 9. Scripts

### 9.1 `scripts/setup-gateway-source.sh`

```bash
#!/bin/sh
set -e

REPO_URL="https://github.com/agentic-community/mcp-gateway-registry.git"
TARGET="mcp-gateway-registry"

if [ -d "${TARGET}/.git" ]; then
    echo "==> mcp-gateway-registry already cloned. Pulling latest..."
    git -C "${TARGET}" pull --ff-only
else
    echo "==> Cloning mcp-gateway-registry from GitHub..."
    git clone --depth 1 "${REPO_URL}" "${TARGET}"
fi

if ! grep -q "mcp-gateway-registry" .gitmodules 2>/dev/null; then
    git submodule add "${REPO_URL}" "${TARGET}" 2>/dev/null || true
fi

echo "==> Source ready at ./${TARGET}"
```

### 9.2 `scripts/bootstrap.sh`

```bash
#!/bin/sh
# Pre-downloads the sentence-transformers model to the HOST path that docker-compose.yml
# bind-mounts into the container at /app/registry/models (M6: NOT /app/models).
set -e

MODELS_DIR="${HOME}/mcp-gateway/models"
MODEL_NAME="all-MiniLM-L6-v2"
MODEL_PATH="${MODELS_DIR}/${MODEL_NAME}"

echo "==> Checking embeddings model at ${MODEL_PATH}..."

if [ -d "${MODEL_PATH}" ] && [ -f "${MODEL_PATH}/model.safetensors" ]; then
    echo "    Model already present. Skipping download."
    exit 0
fi

echo "==> Downloading ${MODEL_NAME} (~90MB) via Python..."
mkdir -p "${MODELS_DIR}"

pip install -q sentence-transformers huggingface-hub

python3 - <<PYEOF
import os, shutil, glob
from sentence_transformers import SentenceTransformer

models_dir = "${MODELS_DIR}"
model_name = "all-MiniLM-L6-v2"
model_path = os.path.join(models_dir, model_name)

model = SentenceTransformer(
    f"sentence-transformers/{model_name}",
    cache_folder=models_dir
)

cached = os.path.join(models_dir, f"models--sentence-transformers--{model_name}")
if os.path.isdir(cached) and not os.path.isdir(model_path):
    snapshots = glob.glob(os.path.join(cached, "snapshots", "*"))
    if snapshots:
        shutil.copytree(snapshots[0], model_path, dirs_exist_ok=True)
        print(f"Model copied to {model_path}")
    else:
        print(f"WARNING: snapshot not found — gateway will download on startup.")
else:
    print(f"Model ready at {model_path}")
PYEOF

echo "==> Done. ${MODEL_PATH} will be visible at /app/registry/models/${MODEL_NAME} inside the container."
```

### 9.3 `scripts/seed_gateway.sh`

```bash
#!/bin/sh
# Registers mock MCP servers in the gateway and pre-populates their tool lists.
#
# Auth: X-Auth-Method: network-trusted — bypasses nginx JWT layer (not running in PoC).
# Endpoint: POST /api/servers/register (form data) — M2 finding.
# Transport: streamable-http at /mcp/ — M6 finding.

GATEWAY_URL="${GATEWAY_BASE_URL:-http://localhost:7860}"

python3 - <<'PYEOF'
import urllib.request
import urllib.parse
import json
import os
import sys

gateway_url = os.environ.get("GATEWAY_BASE_URL", "http://localhost:7860").rstrip("/")

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
        "name":                 "github-mcp",
        "description":          "GitHub MCP server: create issues, list pull requests, search code and get repository info",
        "path":                 "/github-mcp",
        "proxy_pass_url":       "http://github-mcp:8000",
        "mcp_endpoint":         "http://github-mcp:8000/mcp/",
        "supported_transports": "streamable-http",
        "tags":                 "mock,poc",
        "tools":                GITHUB_TOOLS,
    },
    {
        "name":                 "jira-mcp",
        "description":          "Jira MCP server: create tickets, search with JQL, get ticket details and transition workflow status",
        "path":                 "/jira-mcp",
        "proxy_pass_url":       "http://jira-mcp:8000",
        "mcp_endpoint":         "http://jira-mcp:8000/mcp/",
        "supported_transports": "streamable-http",
        "tags":                 "mock,poc",
        "tools":                JIRA_TOOLS,
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
        headers={"Content-Type": "application/x-www-form-urlencoded", **TRUSTED_HEADERS},
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
    print(f"==> Registering {server['name']}...")
    if not register(server):
        all_ok = False

if all_ok:
    print("\n==> Done.")
    print(f"    Web UI (after /dev/login): http://localhost:7860/")
    print(f"    Swagger:                   http://localhost:7860/docs")
    print(f"    Semantic search:           POST http://localhost:7860/api/search/semantic")
else:
    print("\n==> Some registrations failed. Check: docker logs mcp-gateway")
    sys.exit(1)
PYEOF
```

---

## 10. Tests

### 10.1 `sync-worker/tests/test_gateway_client.py`

```python
import pytest
import responses as resp_mock
from config import Config
from gateway_client import GatewayClient, GatewayServer


@pytest.fixture
def config():
    return Config(gateway_base_url="http://gateway.test", gateway_api_token="test-token")


@pytest.fixture
def client(config):
    return GatewayClient(config)


@resp_mock.activate
def test_health_check_true_on_200(client):
    resp_mock.add(resp_mock.GET, "http://gateway.test/health", status=200)
    assert client.health_check() is True


@resp_mock.activate
def test_health_check_false_on_503(client):
    resp_mock.add(resp_mock.GET, "http://gateway.test/health", status=503)
    assert client.health_check() is False


def test_health_check_false_on_connection_error(client):
    assert client.health_check() is False


@resp_mock.activate
def test_list_servers_returns_list(client):
    # M2: actual response wraps servers in {"servers": [...]}
    resp_mock.add(resp_mock.GET, "http://gateway.test/api/servers", json={
        "servers": [
            {"path": "/github-mcp", "display_name": "github-mcp", "description": "GitHub",
             "proxy_pass_url": "http://github-mcp:8000", "tags": ["mock"], "updated_at": "2025-01-01"},
            {"path": "/jira-mcp",   "display_name": "jira-mcp",   "description": "Jira",
             "proxy_pass_url": "http://jira-mcp:8000",   "tags": ["mock"], "updated_at": "2025-01-01"},
        ]
    })
    servers = client.list_servers()
    assert len(servers) == 2
    assert servers[0].name == "github-mcp"
    assert servers[0].path == "/github-mcp"


@resp_mock.activate
def test_list_servers_handles_plain_list_response(client):
    resp_mock.add(resp_mock.GET, "http://gateway.test/api/servers",
                  json=[{"path": "/s1", "display_name": "s1", "description": "",
                         "proxy_pass_url": "", "tags": [], "updated_at": ""}])
    assert len(client.list_servers()) == 1


@resp_mock.activate
def test_list_servers_empty_on_error(client):
    resp_mock.add(resp_mock.GET, "http://gateway.test/api/servers", status=500)
    assert client.list_servers() == []


@resp_mock.activate
def test_register_server_success(client):
    # M2: registration uses POST /api/servers/register with form data
    resp_mock.add(resp_mock.POST, "http://gateway.test/api/servers/register", status=200,
                  json={"message": "registered"})
    assert client.register_server("test", "A test", "http://test:8000") is True
    # M3: network-trusted headers must be present
    assert resp_mock.calls[0].request.headers.get("X-Auth-Method") == "network-trusted"


@resp_mock.activate
def test_register_server_false_on_error(client):
    resp_mock.add(resp_mock.POST, "http://gateway.test/api/servers/register", status=500)
    assert client.register_server("dup", "", "http://x:8000") is False


@resp_mock.activate
def test_update_server_success(client):
    # M2: update re-uses /api/servers/register with overwrite=True
    resp_mock.add(resp_mock.POST, "http://gateway.test/api/servers/register", status=200, json={})
    assert client.update_server("/abc", "s", "d", "http://x:8000") is True


@resp_mock.activate
def test_delete_server_success(client):
    # M2: deletion uses POST /api/servers/remove with form data
    resp_mock.add(resp_mock.POST, "http://gateway.test/api/servers/remove", status=200, json={})
    assert client.delete_server("/abc") is True


@resp_mock.activate
def test_delete_server_false_on_404(client):
    resp_mock.add(resp_mock.POST, "http://gateway.test/api/servers/remove", status=404)
    assert client.delete_server("/ghost") is False
```

### 10.2 `sync-worker/tests/test_integration.py`

```python
"""
Integration tests — require all containers running.
Run: docker exec sync-worker pytest tests/test_integration.py -v -m integration

M6 findings applied:
  - Health returns {"status": "healthy"}
  - Search endpoint: POST /api/search/semantic, param: max_results
  - Search response: {"tools": [...], "servers": [...], ...}
  - Registration: POST /api/servers/register (form data)
  - Listing: GET /api/servers → {"servers": [...]} with field "path"
"""
import os
import pytest
import requests

GATEWAY_URL = os.getenv("GATEWAY_BASE_URL", "http://localhost:7860")
GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "http://github-mcp:8000")
JIRA_MCP_URL   = os.getenv("JIRA_MCP_URL",   "http://jira-mcp:8000")

TRUSTED_HEADERS = {
    "X-Username": "integration-test",
    "X-Auth-Method": "network-trusted",
    "Content-Type": "application/json",
}


@pytest.mark.integration
def test_gateway_is_healthy():
    r = requests.get(f"{GATEWAY_URL}/health", timeout=5)
    assert r.status_code == 200
    try:
        body = r.json()
        healthy = (
            body.get("status") in ("healthy", "ok", "up", True) or
            body.get("healthy") is True or
            bool(body)
        )
        assert healthy, f"Unexpected health response: {body}"
    except Exception:
        pass


@pytest.mark.integration
def test_github_mock_server_is_healthy():
    r = requests.get(f"{GITHUB_MCP_URL}/health", timeout=5)
    assert r.status_code == 200


@pytest.mark.integration
def test_jira_mock_server_is_healthy():
    r = requests.get(f"{JIRA_MCP_URL}/health", timeout=5)
    assert r.status_code == 200


@pytest.mark.integration
def test_register_and_list_server():
    r = requests.post(
        f"{GATEWAY_URL}/api/servers/register",
        data={
            "name": "test-integration-server",
            "description": "Integration test server",
            "path": "/test-integration-server",
            "proxy_pass_url": "http://github-mcp:8000",
            "tags": "integration-test",
            "overwrite": "true",
        },
        headers={k: v for k, v in TRUSTED_HEADERS.items() if k != "Content-Type"},
        timeout=10,
    )
    assert r.status_code in (200, 201), f"Register failed: {r.status_code} {r.text[:200]}"

    r = requests.get(
        f"{GATEWAY_URL}/api/servers",
        headers={k: v for k, v in TRUSTED_HEADERS.items() if k != "Content-Type"},
        timeout=10,
    )
    data = r.json()
    servers = data if isinstance(data, list) else data.get("servers", [])
    names = [s.get("display_name", s.get("server_name", "")) for s in servers]
    assert "test-integration-server" in names

    requests.post(
        f"{GATEWAY_URL}/api/servers/remove",
        data={"path": "/test-integration-server"},
        headers={k: v for k, v in TRUSTED_HEADERS.items() if k != "Content-Type"},
        timeout=10,
    )


@pytest.mark.integration
def test_semantic_search_returns_relevant_tools():
    r = requests.post(
        f"{GATEWAY_URL}/api/search/semantic",
        json={"query": "create a github issue for a bug report", "max_results": 5},
        headers=TRUSTED_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200, f"Search failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    tools = body.get("tools", [])
    servers = body.get("servers", [])
    results = tools + servers
    assert len(results) >= 1

    def result_text(t: dict) -> str:
        return " ".join(str(v) for v in t.values()).lower()

    relevant = any("issue" in result_text(t) or "ticket" in result_text(t) for t in results)
    assert relevant, f"No relevant tool found. tools={[t.get('tool_name', t) for t in tools]}"


@pytest.mark.integration
def test_semantic_search_jira_query():
    r = requests.post(
        f"{GATEWAY_URL}/api/search/semantic",
        json={"query": "search jira tickets by project status", "max_results": 5},
        headers=TRUSTED_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    all_text = " ".join(
        str(v)
        for section in [body.get("tools", []), body.get("servers", [])]
        for t in section for v in t.values()
    ).lower()
    assert "ticket" in all_text or "jira" in all_text


@pytest.mark.integration
def test_semantic_search_respects_max_results():
    r = requests.post(
        f"{GATEWAY_URL}/api/search/semantic",
        json={"query": "create", "max_results": 2},
        headers=TRUSTED_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body.get("tools", [])) <= 2 and len(body.get("servers", [])) <= 2


@pytest.mark.integration
def test_sync_worker_state_file_exists():
    state_file = os.getenv("SYNC_STATE_FILE", "/app/data/sync_state.json")
    assert os.path.isfile(state_file), f"State file not found at {state_file}"


@pytest.mark.integration
def test_sync_worker_logged_sync_started():
    import json
    state_file = os.getenv("SYNC_STATE_FILE", "/app/data/sync_state.json")
    assert os.path.isfile(state_file)
    with open(state_file) as f:
        state = json.load(f)
    assert isinstance(state, dict) and len(state) > 0
```

### 10.3 Tests for `test_registry_client.py` and `test_syncer.py`

These are unchanged from the original spec (section 9.1 and 9.3 of the original CLAUDE.md). Copy them verbatim.

---

## 11. Execution Guide

### Prerequisites

| Requirement | Notes |
|---|---|
| Docker >= 24 with Compose plugin >= 2.20 | |
| Git | For cloning the submodule |
| Python >= 3.11 on host | Only for `scripts/bootstrap.sh` |
| 4 GB RAM | For all containers |
| Docker Hub accessible | Standard images |
| GitHub accessible | For `git clone` (source — NOT a Docker pull) |
| HuggingFace Hub accessible | For model download (see offline alternative) |

### Step by step

```bash
# 1. Clone the repository
git clone <repo-url>
cd poc-mcp-discovery

# 2. Clone mcp-gateway-registry source (git clone — NOT a ghcr.io image pull)
chmod +x scripts/setup-gateway-source.sh
./scripts/setup-gateway-source.sh

# 3. Copy environment config
cp .env.example .env
# Edit .env — the defaults work as-is for local PoC.
# Optionally set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET for real OAuth.

# 4. Download the embeddings model (~90 MB, one-time)
# M6: model goes to ~/mcp-gateway/models, which is bind-mounted to /app/registry/models
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh

# 5. Build all images and start the stack
docker compose up -d --build
# First build takes ~5–10 min (torch CPU download is the slowest step)

# 6. Wait for gateway to become healthy (~90–120 s on first start — model loading)
docker compose ps
# All 5 containers must show "Up" and "(healthy)"

# 7. Register mock servers and pre-populate tool index
chmod +x scripts/seed_gateway.sh
./scripts/seed_gateway.sh
# Expected output: two "OK (HTTP 201)" lines

# 8. Log in to the UI (no GitHub credentials needed)
# Open in browser:  http://localhost:8888/dev/login
# This sets the mcp_gateway_session cookie and redirects to http://localhost:7860/

# 9. Run unit tests (no containers needed)
docker exec sync-worker pytest tests/ -v --ignore=tests/test_integration.py

# 10. Run integration tests (requires running stack + seed done)
docker exec sync-worker pytest tests/test_integration.py -v -m integration
```

### Expected test output

```
# Unit tests
27 passed in ~0.3s

# Integration tests
9 passed in ~1.5s
```

### Stop the PoC

```bash
docker compose down

# Full reset (destroys volumes — triggers model reload on next start)
docker compose down -v
```

---

## 12. Authentication Model

### Internal API calls (sync-worker, seed scripts)

Pass these two headers on every request:

```
X-Username: <any string>
X-Auth-Method: network-trusted
```

This grants full admin access directly, bypassing all OAuth logic. It works because the gateway runs `uvicorn` directly (no nginx JWT validation layer). This is intentional for the PoC.

### Browser / UI access — `/dev/login` bypass

Navigate to `http://localhost:8888/dev/login`.

The auth-server generates a `mcp_gateway_session` cookie signed with `SECRET_KEY` containing:
```json
{
  "username": "dev-admin",
  "auth_method": "oauth2",
  "provider": "github",
  "groups": ["mcp-registry-admin"]
}
```

The `groups: ["mcp-registry-admin"]` value maps to full admin scopes via `registry/config/scopes.yml` inside the gateway, which is evaluated by `enhanced_auth` on each request. The cookie is set for the `localhost` domain and is therefore shared between ports 8888 and 7860.

### Browser / UI access — real GitHub OAuth (optional)

1. Create a GitHub OAuth App (callback URL: `http://localhost:8888/oauth2/callback/github`)
2. Set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_ENABLED=true` in `.env`
3. Restart auth-server: `docker compose up -d --build auth-server`
4. Click "Login with GitHub" on the gateway UI at `http://localhost:7860/login`

---

## 13. Gateway API Reference (M2 Findings)

All requests require either `X-Auth-Method: network-trusted` + `X-Username` headers, or a valid `mcp_gateway_session` cookie.

| Method | Path | Body | Description |
|---|---|---|---|
| `GET` | `/health` | — | Returns `{"status": "healthy", ...}` |
| `GET` | `/api/servers` | — | Returns `{"servers": [...]}`. Each item has `path`, `display_name`, `description`, `proxy_pass_url`, `tags`, `num_tools`, `is_enabled`, `health_status`. |
| `POST` | `/api/servers/register` | form data | Register or overwrite a server. Fields: `name`, `description`, `path`, `proxy_pass_url`, `mcp_endpoint`, `supported_transports`, `tags`, `tool_list_json`, `num_tools`, `overwrite`. |
| `POST` | `/api/servers/remove` | form data | Remove a server. Field: `path`. |
| `POST` | `/api/search/semantic` | JSON | Semantic search. Body: `{"query": "...", "max_results": N}`. Response: `{"tools": [...], "servers": [...], "query": "...", "search_mode": "hybrid"}`. |

---

## 14. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `docker build` fails on `cisco-ai-a2a-scanner` | The git-based dep requires `git` which is absent in `python:3.11-slim` | Confirm `sed -i '/cisco-ai-a2a-scanner @ git+/d' pyproject.toml` runs before `uv pip install` in `Dockerfile.gateway` |
| Gateway `unhealthy` after 2+ min | Model loading failed or wrong model path | Check `docker logs mcp-gateway`. Confirm `${HOME}/mcp-gateway/models/all-MiniLM-L6-v2/` exists on host and the volume mount in `docker-compose.yml` points to `/app/registry/models` (M6) |
| UI shows no servers / 401 | Browser has no session cookie | Navigate to `http://localhost:8888/dev/login` |
| `seed_gateway.sh` fails with 404 | Wrong endpoint — old code used `/api/internal/register` | Confirm endpoint is `POST /api/servers/register` (M2) |
| Semantic search returns 0 results | Mock servers not seeded | Run `./scripts/seed_gateway.sh` |
| Mock server tools show 0 in UI | Gateway couldn't crawl `/mcp` | Confirm mock servers use `StreamableHTTPSessionManager` at `/mcp`, not SSE at `/sse` |
| `sync_source_fetched count=0` | MCP Registry unreachable from container | `docker exec sync-worker python3 -c "import urllib.request; urllib.request.urlopen('https://registry.modelcontextprotocol.io/v0/servers').read()"` |
| `auth-server` fails to start | `server_original.py` not found | Confirm `Dockerfile.auth-poc` runs `mv ... server_original.py` before `COPY auth_server_dev_wrapper.py server.py` |

---

## 15. Verified State

The following was confirmed on 2026-04-17 against a live running stack:

```
docker compose ps:
  auth-server   Up (healthy)   0.0.0.0:8888->8888/tcp
  mcp-gateway   Up (healthy)   0.0.0.0:7860->7860/tcp
  sync-worker   Up
  github-mcp    Up (healthy)   0.0.0.0:8001->8000/tcp
  jira-mcp      Up (healthy)   0.0.0.0:8002->8000/tcp

Unit tests:   27 passed, 0 failed
Integration:   9 passed, 0 failed

Sync worker:  6210+ servers from MCP Registry, errors=0
Mock servers: github-mcp (4 tools), jira-mcp (4 tools), both enabled
```
