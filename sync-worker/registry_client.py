"""
Official MCP Registry client (golden source).
Endpoint: GET /v0/servers — supports cursor-based pagination.
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
