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

