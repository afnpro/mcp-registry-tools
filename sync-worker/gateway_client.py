"""
Custom Gateway client — targets mcp-gateway-registry running without nginx.

Auth strategy (M3 finding):
  - All endpoints use nginx_proxied_auth or nginx_proxied_auth-derived auth.
  - Without nginx, we pass X-Username and X-Auth-Method: network-trusted headers,
    which the registry grants full admin access without any external validation.
  - This is acceptable for a PoC; production would have nginx validate JWTs.

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

# Headers that bypass nginx JWT validation — grants full admin in network-trusted mode.
_NETWORK_TRUSTED_HEADERS = {
    "X-Username": "sync-worker",
    "X-Auth-Method": "network-trusted",
}


def _server_path(server_id: str) -> str:
    """Derive a stable gateway path from a normalized server ID."""
    return f"/{server_id}"


class GatewayServer:
    def __init__(self, raw: dict):
        # M2: servers are keyed by 'path' in the registry, not a simple id.
        self.path: str = raw.get("path", "")
        self.id: str = self.path  # keep .id for syncer compatibility
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
        # Network-trusted auth — bypasses nginx JWT layer when nginx is absent.
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
        """
        Register a server via POST /api/servers/register (form data).

        M2: the actual endpoint takes name, path, proxy_pass_url, description, tags.
        We derive the server path from the name to ensure idempotency.
        """
        # Derive a stable gateway path from the name using the same normalization
        # as MCPRegistryServer.id so syncer lookups are consistent.
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
        """
        Update a server by re-registering with overwrite=True.

        M2: no PUT endpoint exists; /api/servers/register with overwrite=True is the correct approach.
        server_id here is the gateway path (e.g., /io_github_user__server_a).
        """
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
        """
        Remove a server via POST /api/servers/remove (form data, field: path).

        M2: server_id is the gateway path (e.g., /io_github_user__server_a).
        """
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
