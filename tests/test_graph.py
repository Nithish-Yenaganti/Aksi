from pathlib import Path

from graph import (
    UNUSED_HINT_REASON,
    build_architecture,
    component_id,
    external_id,
    file_id,
    refresh_stale_flags,
    write_architecture,
)
from scanner import ImportRef, ScannedFile, ScanResult, scan_repo


def test_graph_builds_hierarchy_and_resolves_local_imports(tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "models.py").write_text("class User:\n    pass\n", encoding="utf-8")
    (package / "app.py").write_text("from pkg.models import User\n\ndef run():\n    return User()\n", encoding="utf-8")

    architecture = build_architecture(scan_repo(tmp_path))
    nodes = architecture["nodes"]

    assert file_id("pkg/app.py") in nodes
    assert file_id("pkg/models.py") in nodes
    assert any(edge["source"] == file_id("pkg/app.py") and edge["target"] == file_id("pkg/models.py") for edge in architecture["edges"])
    assert any(node["type"] == "folder" and node["path"] == "pkg" for node in nodes.values())


def test_graph_refreshes_stale_flags_without_rescanning(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    architecture = write_architecture(tmp_path)

    target.write_text("def run():\n    return 2\n", encoding="utf-8")
    refreshed = refresh_stale_flags(architecture, tmp_path)

    assert refreshed["nodes"][file_id("app.py")]["stale"] is True


def test_graph_marks_possibly_unused_files_and_symbols(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "from used import helper\n\n"
        "def main():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "used.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / "orphan.py").write_text("def abandoned():\n    return 2\n", encoding="utf-8")

    architecture = build_architecture(scan_repo(tmp_path))
    nodes = architecture["nodes"]

    assert nodes[file_id("used.py")]["unused"] is False
    assert nodes[file_id("used.py")]["unused_hint"] is False
    assert nodes[file_id("orphan.py")]["unused"] is True
    assert nodes[file_id("orphan.py")]["unused_hint"] is True
    assert nodes[file_id("orphan.py")]["unused_confidence"] == "low"
    assert nodes[file_id("orphan.py")]["unused_reason"] == UNUSED_HINT_REASON
    assert architecture["analysis"]["unused_files"] == 1
    assert any(
        node["type"] == "function"
        and node["name"] == "abandoned"
        and node["unused"] is True
        and node["unused_hint"] is True
        and node["unused_confidence"] == "low"
        and node["unused_reason"] == UNUSED_HINT_REASON
        for node in nodes.values()
    )
    assert any(
        node["type"] == "function"
        and node["name"] == "helper"
        and node["unused"] is False
        and node["unused_hint"] is False
        for node in nodes.values()
    )


def test_graph_resolves_typescript_extensionless_and_js_imports(tmp_path: Path) -> None:
    (tmp_path / "promptServer.ts").write_text(
        "import { openDb } from './memory/db.js';\n"
        "import { recordFeedback } from './tools/recordFeedback';\n"
        "export function start() { return openDb() && recordFeedback(); }\n",
        encoding="utf-8",
    )
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "db.ts").write_text("export function openDb() { return true; }\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "recordFeedback.ts").write_text(
        "export function recordFeedback() { return true; }\n",
        encoding="utf-8",
    )

    architecture = build_architecture(scan_repo(tmp_path))
    nodes = architecture["nodes"]

    assert any(edge["target"] == file_id("memory/db.ts") for edge in architecture["edges"])
    assert any(edge["target"] == file_id("tools/recordFeedback.ts") for edge in architecture["edges"])
    assert nodes[file_id("memory/db.ts")]["unused"] is False
    assert nodes[file_id("tools/recordFeedback.ts")]["unused"] is False


def test_graph_uses_short_stable_external_ids(tmp_path: Path) -> None:
    long_module = "from graph import " + "very_long_import_name_" * 20
    result = ScanResult(
        repo_path=str(tmp_path),
        files=[
            ScannedFile(
                path="app.py",
                language="python",
                hash="hash",
                imports=[ImportRef(import_text=long_module, module=long_module, start_line=1, end_line=1)],
            )
        ],
        scanner={"version": "test", "files_scanned": 1, "languages": ["python"], "errors": []},
    )

    architecture = build_architecture(result)
    node_id = external_id(long_module)
    edge = architecture["edges"][0]

    assert node_id in architecture["nodes"]
    assert len(node_id) < 90
    assert architecture["nodes"][node_id]["name"] == long_module
    assert edge["target"] == node_id
    assert len(edge["id"]) < 120


def test_graph_builds_project_architecture_components(tmp_path: Path) -> None:
    (tmp_path / "mcp_server.py").write_text("from graph import build\n\ndef serve():\n    return build()\n", encoding="utf-8")
    (tmp_path / "graph.py").write_text("def build():\n    return 1\n", encoding="utf-8")
    (tmp_path / "scanner.py").write_text("def scan():\n    return []\n", encoding="utf-8")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "index.html").write_text("<script>function render() { return true; }</script>", encoding="utf-8")

    architecture = build_architecture(scan_repo(tmp_path))
    nodes = architecture["nodes"]
    component_names = {component["name"] for component in architecture["components"]}

    assert "Agent and MCP Interface" in component_names
    assert "Architecture Graph Builder" in component_names
    assert "Source Scanner" in component_names
    assert "Static Viewer" in component_names
    assert component_id("Architecture Graph Builder") in nodes
    assert nodes[component_id("Static Viewer")]["unused"] is True
    assert nodes[component_id("Static Viewer")]["unused_hint"] is True
    assert nodes[component_id("Static Viewer")]["unused_confidence"] == "low"
    assert nodes[component_id("Static Viewer")]["unused_reason"] == UNUSED_HINT_REASON
    assert nodes[component_id("Static Viewer")]["files"] == ["ui/index.html"]
    assert any(edge["type"] == "component_dependency" for edge in architecture["component_edges"])
