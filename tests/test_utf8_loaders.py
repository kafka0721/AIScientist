"""UTF-8 coverage retained after removal of the scheduled-task tests."""

from __future__ import annotations

import os


def test_production_loaders_accept_utf8_content(tmp_path, monkeypatch):
    from imaging_scientist.langgraph_dev import manager
    from imaging_scientist.mcp import client, registry

    accent = "\u00e9"
    server_name = f"{accent}cho"
    mcp_config = tmp_path / "mcp.yaml"
    mcp_config.write_text(
        (
            f"{server_name}:\n"
            "  transport: stdio\n"
            "  command: python\n"
            f"  args: ['-m', 'd{accent}mo']\n"
            f"  env:\n    MESSAGE: 'bonjour caf{accent}'\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(client, "USER_MCP_CONFIG", mcp_config)
    assert client._load_user_config()[server_name]["env"]["MESSAGE"] == (
        f"bonjour caf{accent}"
    )
    assert client.load_mcp_config()[server_name]["args"] == [
        "-m",
        f"d{accent}mo",
    ]

    marketplace_yaml = tmp_path / f"marketplace-{server_name}.yaml"
    marketplace_yaml.write_text(
        (
            f"name: {server_name}\n"
            f"label: '{server_name} caf{accent}'\n"
            "description: 'localized marketplace entry'\n"
            f"tags: 'd{accent}mo, march{accent}'\n"
            "transport: stdio\n"
            "command: python\n"
            f"args: ['-m', '{server_name}']\n"
        ),
        encoding="utf-8",
    )
    entry = registry.parse_marketplace_yaml(marketplace_yaml)
    assert entry.name == server_name
    assert entry.tags == [f"d{accent}mo", f"march{accent}"]

    venv = tmp_path / "uv" / "tools" / "witaiscientist"
    venv.mkdir(parents=True)
    package = f"mcp-{server_name}"
    (venv / "uv-receipt.toml").write_text(
        (
            "[tool]\nrequirements = [\n"
            "  { name = 'witaiscientist' },\n"
            f"  {{ name = '{package}', specifier = '>=1.0' }},\n]\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    assert registry._uv_tool_existing_requirements()[package] == f"{package}>=1.0"

    runtime = manager.LanggraphRuntimePaths.for_directory(tmp_path / "runtime")
    monkeypatch.setattr(manager, "RUNTIME", runtime)
    workspace = tmp_path / f"workspace-{server_name}"
    manager._write_workspace_sidecar(workspace, 12345)
    assert manager._read_workspace_sidecar() == {
        "workspace": str(workspace),
        "pid": 12345,
    }

    runtime.pid_file.write_text(str(os.getpid()), encoding="utf-8")

    class _NotLanggraphProcess:
        def __init__(self, pid):
            self.pid = pid

        def cmdline(self):
            return ["python", "localized-test"]

        def kill(self):
            raise AssertionError("non-langgraph pid must not be killed")

    monkeypatch.setattr(manager, "_list_pids_on_port", lambda port: [os.getpid()])
    monkeypatch.setattr(manager.psutil, "Process", _NotLanggraphProcess)
    assert manager._kill_owned_stale_process(6174) is False
    assert not runtime.pid_file.exists()
    assert not runtime.workspace_sidecar.exists()
