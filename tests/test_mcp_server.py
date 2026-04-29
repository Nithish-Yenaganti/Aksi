import json
from pathlib import Path

import mcp_server


def test_mcp_helpers_return_expected_shapes(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    scan_summary = mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    file_node = next(node for node in graph["nodes"].values() if node["type"] == "file")
    context = mcp_server.get_context(file_node["id"], str(tmp_path))

    assert scan_summary["summary"]["files"] == 1
    assert scan_summary["viewer_file"].endswith("Files/index.html")
    assert scan_summary["viewer_url"].startswith("file://")
    assert "viewer_http_url" in scan_summary
    assert "viewer_http_error" in scan_summary
    assert scan_summary["summary_mode"] == "host_llm"
    root_target = next(target for target in scan_summary["summary_targets"]["structure"] if target["node_id"] == graph["root"])
    file_target = next(target for target in scan_summary["summary_targets"]["structure"] if target["node_id"] == file_node["id"])
    assert root_target["needs_summary"] is True
    assert root_target["action"] == "write"
    assert file_target["summary_status"] == "missing"
    assert Path(scan_summary["viewer_file"]).exists()
    assert "__AKSI_ARCHITECTURE__" in Path(scan_summary["viewer_file"]).read_text(encoding="utf-8")
    assert scan_summary["summary_index_file"].endswith("Files/context/index.json")
    assert graph["root"] == "repo:."
    assert "def run" in context["source"]


def test_mcp_summary_memory_round_trip_and_stale_detection(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")

    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    function_node = next(node for node in graph["nodes"].values() if node["type"] == "function")

    saved = mcp_server.save_summary(
        function_node["id"],
        {
            "what": "run returns a constant.",
            "why": "It gives tests a simple behavior.",
            "how": "It returns 1 directly.",
            "role": "Small function fixture.",
        },
        str(tmp_path),
    )
    loaded = mcp_server.get_summary(function_node["id"], str(tmp_path))
    listed = mcp_server.list_summaries(str(tmp_path))
    context = mcp_server.get_context(function_node["id"], str(tmp_path))

    assert saved["saved"] is True
    assert loaded["summary"]["what"] == "run returns a constant."
    assert loaded["stale"] is False
    assert function_node["id"] in listed["summaries"]
    assert context["saved_summary"]["summary"]["role"] == "Small function fixture."

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    stale = mcp_server.get_summary(function_node["id"], str(tmp_path))

    assert stale["stale"] is True


def test_mcp_summary_index_keeps_missing_node_records(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path))
    context_dir = tmp_path / "Files" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "old.json").write_text(
        '{"node_id": "file:deleted.py", "summary": "old summary", "file_hash": "old"}',
        encoding="utf-8",
    )

    listed = mcp_server.list_summaries(str(tmp_path))

    assert listed["repo_summary"]
    assert listed["summaries"]["file:deleted.py"]["missing_node"] is True


def test_generate_visualization_preserves_index_only_summaries(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    file_node = next(node for node in graph["nodes"].values() if node["type"] == "file")
    index_path = tmp_path / "Files" / "context" / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "summaries": {
                    file_node["id"]: {
                        "summary": "index-only summary",
                        "path": file_node["path"],
                        "file_hash": file_node["hash"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    mcp_server.generate_visualization(str(tmp_path))
    listed = mcp_server.list_summaries(str(tmp_path))
    loaded = mcp_server.get_summary(file_node["id"], str(tmp_path))
    context = mcp_server.get_context(file_node["id"], str(tmp_path))
    viewer = (tmp_path / "Files" / "index.html").read_text(encoding="utf-8")

    assert listed["summaries"][file_node["id"]]["summary"] == "index-only summary"
    assert listed["summaries"][file_node["id"]]["stale"] is False
    assert loaded["summary"] == "index-only summary"
    assert context["saved_summary"]["summary"] == "index-only summary"
    assert "index-only summary" in viewer


def test_generate_visualization_preserves_saved_summaries_during_refresh(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    first = mcp_server.generate_visualization(str(tmp_path))
    target_ids = [
        target["node_id"]
        for targets in first["summary_targets"].values()
        for target in targets
        if target["type"] in {"repo", "file", "function"}
    ][:3]
    for node_id in target_ids:
        mcp_server.save_summary(node_id, {"what": f"summary for {node_id}"}, str(tmp_path))

    mcp_server.generate_visualization(str(tmp_path))
    listed = mcp_server.list_summaries(str(tmp_path))

    assert set(target_ids).issubset(listed["summaries"])
    assert all(listed["summaries"][node_id]["stale"] is False for node_id in target_ids)


def test_generate_visualization_scans_once(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    original_write_architecture = mcp_server.write_architecture
    calls = 0

    def counted_write_architecture(path):
        nonlocal calls
        calls += 1
        return original_write_architecture(path)

    monkeypatch.setattr(mcp_server, "write_architecture", counted_write_architecture)

    mcp_server.generate_visualization(str(tmp_path))

    assert calls == 1


def test_mcp_returns_context_for_architecture_components(tmp_path: Path) -> None:
    (tmp_path / "mcp_server.py").write_text("from graph import build\n\ndef serve():\n    return build()\n", encoding="utf-8")
    (tmp_path / "graph.py").write_text("def build():\n    return 1\n", encoding="utf-8")

    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    component = next(component for component in graph["components"] if component["name"] == "Agent and MCP Interface")
    context = mcp_server.get_context(component["id"], str(tmp_path))
    saved = mcp_server.save_summary(component["id"], "This component exposes the MCP entrypoint.", str(tmp_path))
    listed = mcp_server.list_summaries(str(tmp_path))

    assert context["node"]["type"] == "component"
    assert "mcp_server.py" in context["source"]
    assert context["sources"][0]["path"] == "mcp_server.py"
    assert context["neighbors"]
    assert saved["saved"] is True
    assert listed["summaries"][component["id"]]["summary"] == "This component exposes the MCP entrypoint."


def test_component_context_limits_large_payloads(tmp_path: Path) -> None:
    for index in range(14):
        (tmp_path / f"module_{index}.py").write_text(
            f"def helper_{index}():\n    return {index}\n",
            encoding="utf-8",
        )

    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    component = next(component for component in graph["components"] if component["name"] == "Application Core")
    context = mcp_server.get_context(component["id"], str(tmp_path))

    assert len(context["sources"]) == mcp_server.MAX_COMPONENT_CONTEXT_FILES
    assert context["context_limit"]["omitted_files"] == 2


def test_stop_viewer_closes_running_viewer_server(tmp_path: Path) -> None:
    class FakeServer:
        def __init__(self) -> None:
            self.shutdown_called = False
            self.close_called = False

        def shutdown(self) -> None:
            self.shutdown_called = True

        def server_close(self) -> None:
            self.close_called = True

    repo = tmp_path.resolve()
    server = FakeServer()
    mcp_server._VIEWER_SERVERS[str(repo)] = (server, 12345)

    stopped = mcp_server.stop_viewer(str(tmp_path))
    stopped_again = mcp_server.stop_viewer(str(tmp_path))

    assert stopped["stopped"] is True
    assert server.shutdown_called is True
    assert server.close_called is True
    assert stopped_again["stopped"] is False


def test_host_refined_models_are_saved_and_embedded_in_viewer(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path))
    model = {
        "nodes": [
            {
                "id": "arch:entry",
                "name": "Entry Layer",
                "type": "architecture_component",
                "summary": "Receives requests.",
                "responsibility": "Start the workflow.",
                "how_it_works": "Calls local code discovered by Aksi.",
                "relationships": "Connects to core.",
                "change_risk": "medium",
                "confidence": "high",
            },
            {"id": "arch:core", "name": "Core Logic", "type": "architecture_component"},
        ],
        "edges": [{"source": "arch:entry", "target": "arch:core", "label": "delegates"}],
    }

    saved = mcp_server.save_architecture_model(model, str(tmp_path))
    models = mcp_server.get_models(str(tmp_path))
    viewer = (tmp_path / "Files" / "index.html").read_text(encoding="utf-8")

    assert saved["saved"] is True
    assert models["models"]["architecture"]["nodes"][0]["name"] == "Entry Layer"
    assert "Entry Layer" in viewer
    assert "__AKSI_MODELS__" in viewer


def test_refined_model_rejects_bad_edges(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path))

    result = mcp_server.save_runtime_model(
        {
            "nodes": [{"id": "runtime:start", "name": "Start"}],
            "edges": [{"source": "runtime:start", "target": "runtime:missing"}],
        },
        str(tmp_path),
    )

    assert "error" in result
    assert result["model_type"] == "runtime"


def test_generate_visualization_returns_host_llm_summary_targets(tmp_path: Path) -> None:
    (tmp_path / "mcp_server.py").write_text("def serve():\n    return True\n", encoding="utf-8")
    (tmp_path / "graph.py").write_text("def build():\n    return 1\n", encoding="utf-8")

    result = mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    component_ids = {component["id"] for component in graph["components"]}
    structure_ids = {target["node_id"] for target in result["summary_targets"]["structure"]}
    architecture_ids = {target["node_id"] for target in result["summary_targets"]["architecture"]}
    runtime_ids = {target["node_id"] for target in result["summary_targets"]["runtime"]}

    assert result["summary_mode"] == "host_llm"
    assert graph["root"] in structure_ids
    assert component_ids.issubset(architecture_ids)
    assert "file:mcp_server.py" in runtime_ids
    assert "file:graph.py" in runtime_ids
    assert "save_summary" in " ".join(result["next_steps"])
    assert "structure" in " ".join(result["summary_workflow"])
    assert "needs_summary" in " ".join(result["summary_workflow"])
    assert set(result["summary_schema"]) == {
        "summary",
        "responsibility",
        "how_it_works",
        "relationships",
        "change_risk",
        "confidence",
    }


def test_generate_visualization_can_disable_summary_targets(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    result = mcp_server.generate_visualization(str(tmp_path), summarize=False)

    assert result["summary_mode"] == "disabled"
    assert result["summary_targets"] == {"structure": [], "architecture": [], "runtime": []}


def test_summary_targets_skip_fresh_and_refresh_changed_nodes(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")

    first = mcp_server.generate_visualization(str(tmp_path))
    file_target = next(target for target in first["summary_targets"]["structure"] if target["type"] == "file")
    assert file_target["summary_status"] == "missing"

    mcp_server.save_summary(file_target["node_id"], {"what": "app module"}, str(tmp_path))
    second = mcp_server.generate_visualization(str(tmp_path))
    fresh_target = next(
        target for target in second["summary_targets"]["structure"] if target["node_id"] == file_target["node_id"]
    )
    assert fresh_target["summary_status"] == "fresh"
    assert fresh_target["needs_summary"] is False
    assert fresh_target["action"] == "skip"

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    third = mcp_server.generate_visualization(str(tmp_path))
    stale_target = next(
        target for target in third["summary_targets"]["structure"] if target["node_id"] == file_target["node_id"]
    )
    assert stale_target["summary_status"] == "stale"
    assert stale_target["needs_summary"] is True
    assert stale_target["action"] == "refresh"


def test_summary_targets_preserve_fresh_and_refresh_only_changed_context(tmp_path: Path) -> None:
    app = tmp_path / "app.py"
    helper = tmp_path / "helper.py"
    app.write_text("from helper import help_me\n\ndef run():\n    return help_me()\n", encoding="utf-8")
    helper.write_text("def help_me():\n    return 1\n", encoding="utf-8")

    first = mcp_server.generate_visualization(str(tmp_path))
    selected_targets = [
        target
        for target in first["summary_targets"]["structure"]
        if target["type"] in {"file", "function"}
    ]
    for target in selected_targets:
        mcp_server.save_summary(target["node_id"], {"what": f"summary for {target['node_id']}"}, str(tmp_path))

    second = mcp_server.generate_visualization(str(tmp_path))
    second_by_id = {
        target["node_id"]: target
        for target in second["summary_targets"]["structure"]
        if target["node_id"] in {item["node_id"] for item in selected_targets}
    }

    assert second_by_id
    assert all(target["summary_status"] == "fresh" for target in second_by_id.values())
    assert all(target["needs_summary"] is False for target in second_by_id.values())

    helper.write_text("def help_me():\n    return 2\n", encoding="utf-8")
    third = mcp_server.generate_visualization(str(tmp_path))
    changed_targets = {
        target["node_id"]: target
        for target in third["summary_targets"]["structure"]
        if target["node_id"] in second_by_id
    }

    assert changed_targets["file:helper.py"]["summary_status"] == "stale"
    assert changed_targets["file:helper.py"]["needs_summary"] is True
    assert changed_targets["file:app.py"]["summary_status"] == "fresh"
    assert changed_targets["file:app.py"]["needs_summary"] is False


def test_get_context_for_folder_returns_child_file_sources(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    folder_node = next(node for node in graph["nodes"].values() if node["type"] == "folder")
    context = mcp_server.get_context(folder_node["id"], str(tmp_path))

    assert context["node"]["type"] == "folder"
    assert context["sources"][0]["path"] == "pkg/app.py"
    assert "def run" in context["source"]
