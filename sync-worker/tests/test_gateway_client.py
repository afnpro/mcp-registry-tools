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
    # M3: network-trusted headers should be present
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
