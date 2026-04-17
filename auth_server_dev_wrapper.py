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
