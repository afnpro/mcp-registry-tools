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
