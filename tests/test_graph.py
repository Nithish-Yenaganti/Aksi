from pathlib import Path

from graph import build_architecture, file_id, refresh_stale_flags, write_architecture
from scanner import scan_repo


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
    assert nodes[file_id("orphan.py")]["unused"] is True
    assert architecture["analysis"]["unused_files"] == 1
    assert any(
        node["type"] == "function" and node["name"] == "abandoned" and node["unused"] is True
        for node in nodes.values()
    )
    assert any(
        node["type"] == "function" and node["name"] == "helper" and node["unused"] is False
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
