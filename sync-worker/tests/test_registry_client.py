import pytest
import responses as resp_mock
from config import Config
from registry_client import MCPRegistryClient


@pytest.fixture
def config():
    return Config(mcp_registry_base_url="https://registry.test",
                  mcp_registry_api_version="v0", mcp_registry_page_size=2)


@pytest.fixture
def client(config):
    return MCPRegistryClient(config)


@resp_mock.activate
def test_list_all_servers_single_page(client):
    resp_mock.add(resp_mock.GET, "https://registry.test/v0/servers", json={
        "servers": [{"server": {"name": "io.github.user/server-a", "description": "A",
                                "repository": {"url": "https://github.com/user/server-a"}, "version": "1.0"},
                     "_meta": {"io.modelcontextprotocol.registry/official":
                                {"status": "active", "updatedAt": "2025-01-01T00:00:00Z"}}}],
        "metadata": {}
    })
    servers = list(client.list_all_servers())
    assert len(servers) == 1
    assert servers[0].name == "io.github.user/server-a"
    assert servers[0].status == "active"
    assert servers[0].updated_at == "2025-01-01T00:00:00Z"


@resp_mock.activate
def test_list_all_servers_pagination(client):
    resp_mock.add(resp_mock.GET, "https://registry.test/v0/servers", json={
        "servers": [{"server": {"name": "s1", "description": "S1", "repository": {}, "version": "1.0"},
                     "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "updatedAt": "2025-01-01"}}}],
        "metadata": {"nextCursor": "cursor-abc"}
    })
    resp_mock.add(resp_mock.GET, "https://registry.test/v0/servers", json={
        "servers": [{"server": {"name": "s2", "description": "S2", "repository": {}, "version": "1.0"},
                     "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "updatedAt": "2025-01-02"}}}],
        "metadata": {}
    })
    servers = list(client.list_all_servers())
    assert len(servers) == 2
    assert {s.name for s in servers} == {"s1", "s2"}


@resp_mock.activate
def test_list_all_servers_empty(client):
    resp_mock.add(resp_mock.GET, "https://registry.test/v0/servers",
                  json={"servers": [], "metadata": {}})
    assert list(client.list_all_servers()) == []


@resp_mock.activate
def test_list_all_servers_http_error_raises(client):
    resp_mock.add(resp_mock.GET, "https://registry.test/v0/servers", status=503)
    with pytest.raises(Exception):
        list(client.list_all_servers())


def test_server_id_normalizes_special_chars():
    from registry_client import MCPRegistryServer
    raw = {"server": {"name": "io.github.user/my-server", "description": "",
                      "repository": {}, "version": "1.0"},
           "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "updatedAt": ""}}}
    s = MCPRegistryServer(raw)
    assert "/" not in s.id
    assert "." not in s.id
