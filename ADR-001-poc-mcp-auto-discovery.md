# ADR-001 — PoC: MCP Tool Auto-Discovery

**Status:** Accepted  
**Date:** 2025-04

## Context

We need to validate that an AI agent can discover relevant tools across multiple MCP servers
via semantic query, without receiving all schemas upfront.

## Decision

Build a Dockerized PoC using:
- **Official MCP Registry** (`registry.modelcontextprotocol.io`) as the public golden source
- **mcp-gateway-registry** (built from source, not pulled from ghcr.io) as the central catalog
- **Sync Worker** (custom, Python) to keep the gateway in sync with the registry
- **Mock MCP Servers** (fastmcp) to simulate a corporate environment

The PoC runs entirely on `python:3.11-slim` base images with `pip` as the only installer,
satisfying the restricted environment constraints (no ghcr.io, no apt, no curl in healthchecks).

## Consequences

- Semantic tool discovery works without schema upfront delivery
- The gateway's auth layer (nginx + JWT) is bypassed via `X-Auth-Method: network-trusted` headers;
  production would use proper OAuth/JWT via nginx
- Security scanning is disabled (`SECURITY_SCAN_ENABLED=false`) because the cisco-ai-a2a-scanner
  CLI tool requires git, which is unavailable in the slim base image
- Model path is `/app/registry/models/<name>` inside the container (bind-mounted from host)
