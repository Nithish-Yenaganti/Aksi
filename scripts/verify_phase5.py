from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.graph import build_graph
from src.engine.scanner import scan_repo
from src.engine.sync import refresh_stale_state


def main() -> None:
    repo = Path("tests/fixtures/phase1_repo")
    target = repo / "web/widget.js"
    original = target.read_text(encoding="utf-8")

    scan_repo(repo, Path("Files/symbols.json"))
    build_graph(Path("Files/symbols.json"), Path("Files/graph.json"))

    try:
        target.write_text(original + "\n// stale marker\n", encoding="utf-8")
        result = refresh_stale_state(Path("Files/symbols.json"), Path("Files/graph.json"))
        assert result["stale_count"] == 1, result
        assert result["stale_files"] == ["web/widget.js"], result
        graph = json.loads(Path("Files/graph.json").read_text(encoding="utf-8"))
        file_node = _find_node(graph["tree"], "file:web/widget.js")
        assert file_node and file_node["stale"] is True, file_node
        assert graph["tree"]["stale"] is True, graph["tree"]
    finally:
        target.write_text(original, encoding="utf-8")

    clean = refresh_stale_state(Path("Files/symbols.json"), Path("Files/graph.json"))
    assert clean["stale_count"] == 0, clean
    print("Phase 5 gate passed: web/widget.js marked stale after change, then clean after restore.")


def _find_node(node: dict[str, object], node_id: str) -> dict[str, object] | None:
    if node.get("id") == node_id:
        return node
    for child in node.get("children", []):
        found = _find_node(child, node_id)
        if found is not None:
            return found
    return None


if __name__ == "__main__":
    main()
