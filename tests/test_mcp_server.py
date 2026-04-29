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
