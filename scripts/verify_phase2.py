from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.graph import build_graph
from src.engine.scanner import scan_repo


def main() -> None:
    symbols_path = Path("Files/symbols.json")
    graph_path = Path("Files/graph.json")

    scan_repo(Path("tests/fixtures/phase1_repo"), symbols_path)
    graph = build_graph(symbols_path, graph_path)
    data = graph.to_dict()

    assert graph_path.exists(), "graph.json was not written"
    assert data["tree"]["kind"] == "project"
    assert _find_node(data["tree"], "folder:web"), "web folder missing from hierarchy"
    assert _find_node(data["tree"], "file:web/widget.js"), "widget file missing from hierarchy"
    assert _find_node(data["tree"], "function:web/widget.js:renderWidget"), "renderWidget function missing from hierarchy"

    edges = {(edge["source_path"], edge["target_path"], edge["import_name"]) for edge in data["edges"]}
    assert ("pkg/service.py", "web/widget.js", "renderWidget") in edges, edges
    assert ("web/widget.js", "web/label.ts", "{ label }") in edges, edges

    print(json.dumps(data, indent=2, sort_keys=True))
    print("\nPhase 2 graph edges:")
    for edge in data["edges"]:
        print(f"{edge['source_path']} -> {edge['target_path']} ({edge['import_module']}:{edge['import_name']})")
    print(f"\nPhase 2 gate passed: wrote {graph_path} with {len(data['edges'])} edge(s).")


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
