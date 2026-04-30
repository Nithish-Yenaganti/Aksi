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
    assert scan_summary["viewer_url"] is None
    assert scan_summary["viewer_http_url"] is None
    assert scan_summary["viewer_http_error"] == "withheld_until_summary_and_model_refinement_complete"
    assert scan_summary["viewer_release"]["complete"] is False
    assert scan_summary["viewer_release"]["withheld"] is True
    assert scan_summary["summary_mode"] == "host_llm_worklist"
    assert scan_summary["summary_behavior"]["automatic_summaries"] is False
    assert scan_summary["summary_behavior"]["written_by_aksi"] == 0
    assert scan_summary["host_llm_required"] is True
    assert scan_summary["summary_status"]["work_items"] == len(scan_summary["summary_worklist"])
    assert scan_summary["summary_completion"]["required"] is True
    assert scan_summary["summary_completion"]["complete"] is False
    assert scan_summary["summary_completion"]["remaining"] == len(scan_summary["summary_worklist"])
    assert scan_summary["summary_completion"]["viewer_state"] == "graph_ready_summaries_pending"
    assert scan_summary["summaries_complete"] is False
    assert scan_summary["model_refinement"]["architecture_required"] is True
    assert scan_summary["model_refinement"]["runtime_required"] is True
    assert scan_summary["model_refinement"]["complete"] is False
    assert scan_summary["model_refinement"]["source"] == "local_candidates_need_host_refinement"
    root_target = next(target for target in scan_summary["summary_targets"]["structure"] if target["node_id"] == graph["root"])
    file_target = next(target for target in scan_summary["summary_targets"]["structure"] if target["node_id"] == file_node["id"])
    assert root_target["needs_summary"] is True
    assert root_target["action"] == "write"
    assert file_target["summary_status"] == "missing"
    assert Path(scan_summary["viewer_file"]).exists()
    viewer = Path(scan_summary["viewer_file"]).read_text(encoding="utf-8")
    assert "__AKSI_ARCHITECTURE__" in viewer
    assert 'id="searchBox"' in viewer
    assert 'data-filter="missing"' in viewer
    assert "function nodeHasDisplaySummary" in viewer
    assert "return !nodeHasDisplaySummary(node)" in viewer
    assert "Export SVG" in viewer
    assert "Export PNG" in viewer
    assert "Copy Summary" in viewer
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


def test_viewer_template_path_supports_installed_data_file(tmp_path: Path, monkeypatch) -> None:
    installed_template = tmp_path / "share" / "aksi" / "ui" / "index.html"
    installed_template.parent.mkdir(parents=True)
    installed_template.write_text("installed template", encoding="utf-8")

    monkeypatch.setattr(mcp_server, "_aksi_root", lambda: tmp_path / "missing")
    monkeypatch.setattr(mcp_server.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(mcp_server.sys, "base_prefix", str(tmp_path))

    assert mcp_server._viewer_template_path() == installed_template


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
    source = tmp_path / "app.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path))
    model = {
        "nodes": [
            {
                "id": "arch:entry",
                "name": "Entry Layer",
                "type": "architecture_component",
                "purpose": "Receives requests.",
                "behavior": "Starts the workflow.",
                "interfaces": "Public entrypoint.",
                "dependencies": "Core logic.",
                "used_by": "External callers.",
                "change_risk": "medium",
                "open_questions": "Confirm external callers.",
                "confidence": "high",
            },
            {"id": "arch:core", "name": "Core Logic", "type": "architecture_component"},
        ],
        "edges": [{"source": "arch:entry", "target": "arch:core", "label": "delegates"}],
    }

    saved = mcp_server.save_architecture_model(model, str(tmp_path))
    runtime_model = {
        "nodes": [
            {"id": "runtime:start", "name": "Start", "type": "runtime_step"},
            {"id": "runtime:finish", "name": "Finish", "type": "runtime_step"},
        ],
        "edges": [{"source": "runtime:start", "target": "runtime:finish", "label": "then"}],
    }
    runtime_saved = mcp_server.save_runtime_model(runtime_model, str(tmp_path))
    models = mcp_server.get_models(str(tmp_path))
    refreshed = mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)
    viewer = (tmp_path / "Files" / "index.html").read_text(encoding="utf-8")

    assert saved["saved"] is True
    assert runtime_saved["saved"] is True
    assert "source_graph_hash" in saved["model"]
    assert "source_graph_hash" in runtime_saved["model"]
    assert models["models"]["architecture"]["nodes"][0]["name"] == "Entry Layer"
    assert models["models"]["runtime"]["nodes"][0]["name"] == "Start"
    assert refreshed["model_refinement"]["complete"] is True
    assert refreshed["model_refinement"]["architecture_required"] is False
    assert refreshed["model_refinement"]["runtime_required"] is False
    assert refreshed["model_refinement"]["current_models"] == {"architecture": True, "runtime": True}
    assert refreshed["model_refinement"]["stale_models"] == {"architecture": False, "runtime": False}
    assert "Entry Layer" in viewer
    assert "__AKSI_MODELS__" in viewer

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    changed = mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    assert changed["model_refinement"]["complete"] is False
    assert changed["model_refinement"]["architecture_required"] is True
    assert changed["model_refinement"]["runtime_required"] is True
    assert changed["model_refinement"]["saved_models"] == {"architecture": True, "runtime": True}
    assert changed["model_refinement"]["current_models"] == {"architecture": False, "runtime": False}
    assert changed["model_refinement"]["stale_models"] == {"architecture": True, "runtime": True}


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

    assert result["summary_mode"] == "host_llm_worklist"
    assert graph["root"] in structure_ids
    assert component_ids.issubset(architecture_ids)
    assert "file:mcp_server.py" in runtime_ids
    assert "file:graph.py" in runtime_ids
    assert "save_summary" in " ".join(result["next_steps"])
    assert result["next_steps"][0].startswith("Inspect summary_mode")
    assert "viewer_http_url and viewer_url are withheld" in " ".join(result["next_steps"])
    assert "do not clear summary_worklist" in " ".join(result["next_steps"])
    assert "Verify each summary matches the exact get_context node" in " ".join(result["next_steps"])
    assert "model_refinement" in result
    assert "After summaries are current, inspect model_refinement" in " ".join(result["next_steps"])
    assert "grounded get_map/get_context" in " ".join(result["refinement_workflow"])
    assert "Refined models do not clear summary_worklist" in " ".join(result["refinement_workflow"])
    assert "summary_worklist" in " ".join(result["summary_workflow"])
    assert "verify_summary_matches_context" in " ".join(result["summary_workflow"])
    assert result["summary_worklist"]
    assert len({target["node_id"] for target in result["summary_worklist"]}) == len(result["summary_worklist"])
    assert set(result["summary_schema"]) == {
        "purpose",
        "behavior",
        "interfaces",
        "dependencies",
        "used_by",
        "change_risk",
        "open_questions",
        "confidence",
    }


def test_generate_visualization_compact_response_omits_large_payloads(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    result = mcp_server.generate_visualization(str(tmp_path), response_mode="compact", serve_viewer=False)

    assert result["response_mode"] == "compact"
    assert result["next_action"] == "summarize_batch"
    assert result["recommended_batch"]["tool"] == "get_summary_context_bundle"
    assert result["recommended_batch"]["limit"] == 15
    assert "summary_targets" not in result
    assert "summary_worklist" not in result
    assert result["omitted"]["summary_targets"] is True
    assert result["omitted"]["summary_worklist"] is True


def test_generate_visualization_can_disable_summary_targets(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    result = mcp_server.generate_visualization(str(tmp_path), summarize=False)
    status = mcp_server.get_workflow_status(str(tmp_path), prepare_summary_targets=False)

    assert result["summary_mode"] == "disabled"
    assert result["summary_targets"] == {"structure": [], "architecture": [], "runtime": []}
    assert result["summary_worklist"] == []
    assert result["host_llm_required"] is False
    assert result["summary_completion"]["complete"] is True
    assert result["summary_completion"]["required"] is False
    assert result["summaries_complete"] is True
    assert status["summary"]["mode"] == "disabled"
    assert status["summary"]["complete"] is True
    assert status["summary"]["remaining"] == 0
    assert status["next_action"] == "refine_models"


def test_workflow_status_compact_omits_worklist_and_limits_batch(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    generated = mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    status = mcp_server.get_workflow_status(str(tmp_path), response_mode="compact")

    assert status["response_mode"] == "compact"
    assert "summary_worklist" not in status
    assert status["summary"]["worklist_omitted"] is True
    assert status["summary"]["work_items"] == len(generated["summary_worklist"])
    assert status["recommended_batch"]["limit"] == 15
    assert len(status["recommended_batch"]["node_ids"]) == min(15, len(generated["summary_worklist"]))


def test_generate_visualization_prepare_summary_targets_alias(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    disabled = mcp_server.generate_visualization(str(tmp_path), summarize=True, prepare_summary_targets=False)
    enabled = mcp_server.generate_visualization(str(tmp_path), summarize=False, prepare_summary_targets=True)

    assert disabled["summary_mode"] == "disabled"
    assert disabled["summary_worklist"] == []
    assert enabled["summary_mode"] == "host_llm_worklist"
    assert enabled["summary_worklist"]


def test_get_summary_worklist_returns_deduplicated_missing_and_stale_nodes(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")

    first = mcp_server.generate_visualization(str(tmp_path))
    file_item = next(item for item in first["summary_worklist"] if item["type"] == "file")
    mcp_server.save_summary(file_item["node_id"], {"summary": "app module"}, str(tmp_path))

    second = mcp_server.get_summary_worklist(str(tmp_path))
    second_ids = {item["node_id"] for item in second["summary_worklist"]}
    assert file_item["node_id"] not in second_ids
    assert second["summary_completion"]["remaining"] == len(second["summary_worklist"])

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    third = mcp_server.get_summary_worklist(str(tmp_path))
    third_by_id = {item["node_id"]: item for item in third["summary_worklist"]}

    assert third_by_id[file_item["node_id"]]["summary_status"] == "stale"
    assert third_by_id[file_item["node_id"]]["action"] == "refresh"
    assert len(third_by_id) == len(third["summary_worklist"])


def test_get_context_batch_defaults_to_worklist_and_reports_limits(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    generated = mcp_server.generate_visualization(str(tmp_path))
    batch = mcp_server.get_context_batch(path=str(tmp_path), limit=2)
    bundle = mcp_server.get_summary_context_bundle(str(tmp_path), include_source=False)

    assert batch["batch"]["defaulted_to_worklist"] is True
    assert batch["batch"]["requested"] == len(generated["summary_worklist"])
    assert batch["batch"]["returned"] == 2
    assert batch["batch"]["truncated"] is True
    assert len(batch["contexts"]) == 2
    assert len(batch["items"]) == 2
    assert batch["errors"] == []
    assert all(item["context"]["node"]["id"] == item["node_id"] for item in batch["items"])
    assert bundle["batch"]["include_source"] is False
    assert bundle["contexts"]
    assert all(context["source"] == "" for context in bundle["contexts"].values())
    assert all(context["context_stats"]["source_included"] is False for context in bundle["contexts"].values())


def test_get_context_batch_accepts_explicit_nodes_and_partial_errors(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    mcp_server.generate_visualization(str(tmp_path))
    graph = mcp_server.get_map(str(tmp_path))
    file_node = next(node for node in graph["nodes"].values() if node["type"] == "file")
    batch = mcp_server.get_context_batch([file_node["id"], "file:missing.py"], str(tmp_path))

    assert file_node["id"] in batch["contexts"]
    assert batch["contexts"][file_node["id"]]["node"]["id"] == file_node["id"]
    assert batch["errors"] == [{"node_id": "file:missing.py", "error": "Node not found: file:missing.py"}]
    assert batch["batch"]["successes"] == 1
    assert batch["batch"]["errors"] == 1


def test_read_only_tools_do_not_regenerate_viewer_or_index(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)
    viewer_path = tmp_path / "Files" / "index.html"
    index_path = tmp_path / "Files" / "context" / "index.json"
    original_viewer = viewer_path.read_text(encoding="utf-8")
    original_index = index_path.read_text(encoding="utf-8")

    mcp_server.get_map(str(tmp_path))
    mcp_server.get_summary_worklist(str(tmp_path))
    mcp_server.get_workflow_status(str(tmp_path), response_mode="compact")
    mcp_server.get_context_batch(path=str(tmp_path), limit=1, include_source=False)
    mcp_server.get_digest(str(tmp_path))
    mcp_server.list_summaries(str(tmp_path))

    assert viewer_path.read_text(encoding="utf-8") == original_viewer
    assert index_path.read_text(encoding="utf-8") == original_index


def _save_all_worklist_summaries(path: Path) -> None:
    worklist = mcp_server.get_summary_worklist(str(path))["summary_worklist"]
    mcp_server.save_summaries(
        [
            {
                "node_id": item["node_id"],
                "summary": {
                    "purpose": f"Summary for {item['node_id']}.",
                    "behavior": "Grounded test summary.",
                    "interfaces": "Test fixture.",
                    "dependencies": "Scanned graph context.",
                    "used_by": "MCP workflow tests.",
                    "change_risk": "low: test fixture.",
                    "open_questions": "None.",
                    "confidence": "high",
                },
            }
            for item in worklist
        ],
        str(path),
    )


def _save_current_test_models(path: Path) -> None:
    mcp_server.save_architecture_model(
        {"nodes": [{"id": "architecture:test", "name": "Test Architecture"}], "edges": []},
        str(path),
    )
    mcp_server.save_runtime_model(
        {"nodes": [{"id": "runtime:test", "name": "Test Runtime"}], "edges": []},
        str(path),
    )


def test_get_workflow_status_recommends_summary_batch_and_withholds_viewer(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    generated = mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    status = mcp_server.get_workflow_status(str(tmp_path), limit=2)

    assert status["next_action"] == "summarize_batch"
    assert status["summary"]["complete"] is False
    assert status["summary"]["remaining"] == len(generated["summary_worklist"])
    assert status["summary"]["missing"] == len(generated["summary_worklist"])
    assert status["summary"]["stale"] == 0
    assert status["recommended_batch"]["tool"] == "get_summary_context_bundle"
    assert status["recommended_batch"]["fallback_tool"] == "get_context_batch"
    assert len(status["recommended_batch"]["node_ids"]) == 2
    assert status["recommended_batch"]["truncated"] is True
    assert status["viewer"]["releasable"] is False
    assert "viewer_url" not in status["viewer"]
    assert "viewer_http_url" not in status["viewer"]
    assert "summary_worklist has" in status["viewer"]["withheld_reason"]
    assert status["instructions"] == [
        "Call get_summary_context_bundle(path=path, limit=limit) for recommended_batch.node_ids.",
        "Write and verify one grounded summary per returned context.",
        "Call save_summaries(items, path=path) once for the batch.",
        "Call get_workflow_status(path=path, limit=limit) again.",
    ]


def test_get_workflow_status_recommends_model_refinement_after_summaries(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)
    _save_all_worklist_summaries(tmp_path)

    status = mcp_server.get_workflow_status(str(tmp_path))

    assert status["next_action"] == "refine_models"
    assert status["summary"]["complete"] is True
    assert status["summary"]["remaining"] == 0
    assert status["recommended_batch"]["tool"] is None
    assert status["model"]["complete"] is False
    assert status["model"]["architecture_required"] is True
    assert status["model"]["runtime_required"] is True
    assert status["model"]["seed_tool"] == "get_model_seed"
    assert status["viewer"]["releasable"] is False
    assert "required models: architecture, runtime" in status["viewer"]["withheld_reason"]
    assert status["instructions"][0].startswith("Call get_model_seed")


def test_get_model_seed_returns_compact_refinement_facts(tmp_path: Path) -> None:
    (tmp_path / "server.ts").write_text(
        "import debounce from 'lodash';\n"
        "import { helper } from './utils';\n"
        "export function start() {\n"
        "  return debounce(helper, 10)();\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.ts").write_text("export function helper() {\n  return 'ok';\n}\n", encoding="utf-8")
    (tmp_path / "settings.json").write_text('{"feature": true}\n', encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    seed = mcp_server.get_model_seed(str(tmp_path))

    assert seed["source"] == "local_seed_for_host_llm_refinement"
    assert seed["llm_called_by_aksi"] is False
    assert seed["repo"]["counts"]["files"] == 2
    assert seed["model_refinement"]["architecture_required"] is True
    assert seed["model_refinement"]["runtime_required"] is True
    assert seed["suggested_next"]["tool"] == "get_summary_context_bundle"
    assert seed["architecture_seed"]["components"]
    assert seed["architecture_seed"]["component_edges"] or seed["runtime_seed"]["dependency_edges"]
    assert seed["runtime_seed"]["kind"] == "static_dependency_flow_seed"
    assert "lodash" in seed["runtime_seed"]["unresolved_externals"]
    assert any(item["path"] == "server.ts" for item in seed["architecture_seed"]["entrypoints"])
    assert any(item["path"] == "server.ts" for item in seed["key_files"])
    assert "get_context_batch" == seed["required_context"]["recommended_tool"]
    assert seed["architecture_candidates"]["components"]
    assert seed["architecture_candidates"]["evidence_files"]
    assert seed["architecture_candidates"]["component_edges"] or seed["runtime_candidates"]["ordered_flows"]
    assert seed["architecture_candidates"]["confidence"] in {"high", "medium", "low"}
    first_component = seed["architecture_candidates"]["components"][0]
    assert "evidence_files" in first_component
    assert "component_edges" in first_component
    assert first_component["confidence"] in {"high", "medium", "low"}
    assert any(item["path"] == "server.ts" for item in seed["architecture_candidates"]["evidence_files"])
    assert any(item["path"] == "server.ts" for item in seed["runtime_candidates"]["entrypoints"])
    assert seed["runtime_candidates"]["ordered_flows"]
    assert seed["runtime_candidates"]["external_dependencies"] == seed["runtime_seed"]["external_dependencies"]
    assert "lodash" in seed["runtime_candidates"]["external_dependencies"]
    assert any(item["path"] == "settings.json" for item in seed["runtime_candidates"]["data_artifacts"])
    assert seed["runtime_candidates"]["confidence"] in {"high", "medium", "low"}
    assert "file:server.ts" in seed["recommended_context"]["must_read"]
    assert seed["recommended_context"]["optional"]
    assert seed["recommended_context"]["recommended_tool"] == "get_context_batch"
    assert seed["recommended_context"]["reason"]
    assert "nodes" in seed["model_shape"]
    assert "edges" in seed["model_shape"]


def test_get_digest_returns_compact_local_static_repo_facts(tmp_path: Path) -> None:
    (tmp_path / "server.ts").write_text(
        "import debounce from 'lodash';\n"
        "import { helper } from './utils';\n"
        "export function start() {\n"
        "  return debounce(helper, 10)();\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "utils.ts").write_text("export function helper() {\n  return 'ok';\n}\n", encoding="utf-8")
    (tmp_path / "orphan.py").write_text("def abandoned():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    digest = mcp_server.get_digest(str(tmp_path))

    assert digest["mode"] == "brief"
    assert digest["source"] == "local_static_digest"
    assert digest["llm_called_by_aksi"] is False
    assert "local/static" in digest["guess_policy"]
    assert digest["repo"]["name"] == tmp_path.name
    assert digest["repo"]["purpose"]
    assert digest["repo"]["languages"] == {"python": 1, "typescript": 2}
    assert digest["repo"]["counts"]["files"] == 3
    assert digest["workflow"]["next_action"] == "summarize_batch"
    assert digest["workflow"]["next_tool"] == "get_summary_context_bundle"
    assert digest["workflow"]["viewer_releasable"] is False
    assert digest["workflow"]["viewer_url"] is None
    assert digest["summary_completion"]["required"] is True
    assert digest["model_refinement"]["architecture_required"] is True
    assert any(item["path"] == "server.ts" for item in digest["entrypoints"])
    assert digest["major_components"]
    assert digest["runtime_flow_guess"]["kind"] == "local/static dependency flow guess"
    assert "lodash" in digest["runtime_flow_guess"]["external_dependencies"]
    assert any(item["path"] == "orphan.py" for item in digest["unused_hints"]["files"])
    assert any(item["name"] == "abandoned" for item in digest["unused_hints"]["symbols"])
    assert any(item["path"] == "server.ts" for item in digest["next_files_to_inspect"])


def test_get_digest_reports_stale_files_from_saved_graph(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)

    source.write_text("def run():\n    return 2\n", encoding="utf-8")
    digest = mcp_server.get_digest(str(tmp_path), mode="full")

    assert digest["mode"] == "full"
    assert digest["repo"]["counts"]["stale_files"] == 1
    assert digest["stale_files"][0]["path"] == "app.py"
    assert any(risk["label"] == "stale_files" for risk in digest["risks"])
    inspect_item = next(item for item in digest["next_files_to_inspect"] if item["path"] == "app.py")
    assert "stale_on_disk" in inspect_item["local_static_reasons"]


def test_get_workflow_status_releases_viewer_when_complete(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    mcp_server.generate_visualization(str(tmp_path), serve_viewer=False)
    _save_all_worklist_summaries(tmp_path)
    _save_current_test_models(tmp_path)

    status = mcp_server.get_workflow_status(str(tmp_path))

    assert status["next_action"] == "release_viewer"
    assert status["summary"]["complete"] is True
    assert status["model"]["complete"] is True
    assert status["model"]["current_models"] == {"architecture": True, "runtime": True}
    assert status["viewer"]["releasable"] is True
    assert status["viewer"]["withheld"] is False
    assert status["viewer"]["withheld_reason"] is None
    assert status["viewer"]["viewer_url"].startswith("file://")
    if status["viewer"]["viewer_http_url"] is None:
        assert status["viewer"]["viewer_http_error"]
    else:
        assert status["viewer"]["viewer_http_url"].startswith("http://127.0.0.1:")
    assert status["instructions"] == [
        "Use viewer_http_url when present, otherwise use viewer_url.",
        "Share the viewer link with the user.",
    ]

    mcp_server.stop_viewer(str(tmp_path))


def test_save_summaries_saves_batch_with_partial_failure_and_shrinks_worklist(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")

    generated = mcp_server.generate_visualization(str(tmp_path))
    targets = generated["summary_worklist"][:2]
    saved = mcp_server.save_summaries(
        [
            {"node_id": targets[0]["node_id"], "summary": {"purpose": "first summary"}},
            {"node_id": "file:missing.py", "summary": {"purpose": "missing node"}},
            {"node_id": targets[1]["node_id"], "summary": {"purpose": "second summary"}},
        ],
        str(tmp_path),
    )
    worklist_after = mcp_server.get_summary_worklist(str(tmp_path))
    remaining_ids = {item["node_id"] for item in worklist_after["summary_worklist"]}
    listed = mcp_server.list_summaries(str(tmp_path))
    viewer = (tmp_path / "Files" / "index.html").read_text(encoding="utf-8")

    assert saved["saved"] == 2
    assert saved["failed"] == 1
    assert saved["errors"][0]["node_id"] == "file:missing.py"
    assert targets[0]["node_id"] not in remaining_ids
    assert targets[1]["node_id"] not in remaining_ids
    assert worklist_after["summary_completion"]["remaining"] == len(generated["summary_worklist"]) - 2
    assert listed["summaries"][targets[0]["node_id"]]["summary"] == {"purpose": "first summary"}
    assert "first summary" in viewer


def test_save_summaries_reports_invalid_items_without_refreshing(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    generated = mcp_server.generate_visualization(str(tmp_path))

    saved = mcp_server.save_summaries(
        [
            {"node_id": generated["summary_worklist"][0]["node_id"]},
            {"node_id": "", "summary": "empty id"},
            "not a dict",
        ],
        str(tmp_path),
    )

    assert saved["saved"] == 0
    assert saved["failed"] == 3
    assert saved["summary_completion"]["remaining"] == len(generated["summary_worklist"])


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
