import json
import pytest
from unittest.mock import MagicMock
from syncer import run_sync
from registry_client import MCPRegistryServer
from gateway_client import GatewayServer


def make_registry_server(name, updated_at="2025-01-01T00:00:00Z", status="active"):
    raw = {"server": {"name": name, "description": f"Desc {name}",
                      "repository": {"url": f"https://github.com/test/{name}"}, "version": "1.0"},
           "_meta": {"io.modelcontextprotocol.registry/official":
                     {"status": status, "updatedAt": updated_at}}}
    return MCPRegistryServer(raw)


def make_gateway_server(path, display_name, tags=None):
    # M2: gateway servers have path as primary identifier; GatewayServer.id == path
    return GatewayServer({"path": path, "display_name": display_name, "description": "",
                          "proxy_pass_url": "http://placeholder", "updated_at": "2025-01-01",
                          "tags": tags or ["auto-synced"]})


def test_adds_new_server(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([make_registry_server("server-new")])
    gateway.list_servers.return_value = []
    gateway.register_server.return_value = True
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["added"] == 1 and metrics["errors"] == 0
    gateway.register_server.assert_called_once()


def test_adds_multiple_servers(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([
        make_registry_server("a"), make_registry_server("b"), make_registry_server("c")])
    gateway.list_servers.return_value = []
    gateway.register_server.return_value = True
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["added"] == 3


def test_add_failure_increments_errors(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([make_registry_server("fail")])
    gateway.list_servers.return_value = []
    gateway.register_server.return_value = False
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["added"] == 0 and metrics["errors"] == 1


def test_updates_changed_server(tmp_path):
    state_file = str(tmp_path / "state.json")
    with open(state_file, "w") as f:
        json.dump({"io_github_test__server-a": "2025-01-01T00:00:00Z"}, f)
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([
        make_registry_server("io.github.test/server-a", updated_at="2025-02-01T00:00:00Z")])
    gateway.list_servers.return_value = [
        make_gateway_server("/io_github_test__server-a", "io.github.test/server-a")]
    gateway.update_server.return_value = True
    metrics = run_sync(registry, gateway, state_file)
    assert metrics["updated"] == 1


def test_does_not_update_unchanged_server(tmp_path):
    state_file = str(tmp_path / "state.json")
    same_ts = "2025-01-01T00:00:00Z"
    with open(state_file, "w") as f:
        json.dump({"io_github_test__server-a": same_ts}, f)
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([
        make_registry_server("io.github.test/server-a", updated_at=same_ts)])
    gateway.list_servers.return_value = [
        make_gateway_server("/io_github_test__server-a", "io.github.test/server-a")]
    metrics = run_sync(registry, gateway, state_file)
    assert metrics["updated"] == 0
    gateway.update_server.assert_not_called()


def test_deletes_removed_server(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([])
    gateway.list_servers.return_value = [
        make_gateway_server("/old", "old", tags=["auto-synced"])]
    gateway.delete_server.return_value = True
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["deleted"] == 1
    gateway.delete_server.assert_called_once_with("/old")


def test_does_not_delete_manually_registered_server(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([])
    gateway.list_servers.return_value = [
        make_gateway_server("/manual", "manual", tags=["manual"])]
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["deleted"] == 0
    gateway.delete_server.assert_not_called()


def test_skips_inactive_servers(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([
        make_registry_server("deprecated", status="deprecated")])
    gateway.list_servers.return_value = []
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["added"] == 0
    gateway.register_server.assert_not_called()


def test_persists_state_after_run(tmp_path):
    state_file = str(tmp_path / "state.json")
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([
        make_registry_server("server-x", updated_at="2025-03-01T00:00:00Z")])
    gateway.list_servers.return_value = []
    gateway.register_server.return_value = True
    run_sync(registry, gateway, state_file)
    with open(state_file) as f:
        state = json.load(f)
    assert any("2025-03-01T00:00:00Z" in v for v in state.values())


def test_registry_error_returns_early(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.side_effect = Exception("Registry unreachable")
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert metrics["errors"] == 1
    gateway.register_server.assert_not_called()


def test_metrics_contain_timestamps(tmp_path):
    registry, gateway = MagicMock(), MagicMock()
    registry.list_all_servers.return_value = iter([])
    gateway.list_servers.return_value = []
    metrics = run_sync(registry, gateway, str(tmp_path / "state.json"))
    assert "started_at" in metrics and "finished_at" in metrics
