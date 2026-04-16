"""
Diff and upsert logic between the MCP Registry (golden source) and the gateway.

Algorithm:
1. Fetch all active servers from MCP Registry
2. Fetch all servers currently in gateway
3. Compute add / update / delete sets
4. Apply operations
5. Persist state (server_id -> updated_at) for incremental diff

M2 note: gateway servers are identified by 'path' (e.g. /io_github_user__server_a),
not a numeric id. GatewayServer.id == GatewayServer.path.
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

    # M2: gateway servers are keyed by path; GatewayServer.id == path (e.g. /io_github__server_a).
    # We match on display_name to find existing registrations.
    all_gateway = gateway_client.list_servers()
    current_gateway = {s.name: s for s in all_gateway}
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
            # M2: update uses the gateway path (server_id field on GatewayServer == path)
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
                # Remove from state using the normalized server_id (name → id normalization).
                normalized_id = gw_server.name.replace("/", "__").replace(".", "_")
                new_state.pop(normalized_id, None)
            else:
                metrics["errors"] += 1

    _save_state(state_file, new_state)
    metrics["finished_at"] = datetime.now(timezone.utc).isoformat()
    log.info("sync_finished", **metrics)
    return metrics
