from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi.graph import build_project_graph, write_graph
from aksi.scanner import scan_repo, write_symbols


def main() -> None:
    repo = Path("tests/fixtures/polyglot")
    symbols_output = Path("Files/symbols.json")
    graph_output = Path("Files/index.json")

    index = scan_repo(repo)
    graph = build_project_graph(index)
    write_symbols(index, symbols_output)
    write_graph(graph, graph_output)

    edge_pairs = {(edge.source_path, edge.target_path, edge.import_name) for edge in graph.edges}
    assert ("src/greeter.py", "web/message.js", "buildMessage") in edge_pairs, edge_pairs
    assert ("web/message.js", "src/greeter.py", "{ DEFAULT_NAME }") in edge_pairs, edge_pairs

    print(json.dumps(graph.to_json_dict(), indent=2, sort_keys=True))
    print("\nPhase 2 verified graph edges:")
    for edge in graph.edges:
        print(f"{edge.source_path} -> {edge.target_path} ({edge.import_module}:{edge.import_name})")
    print(f"\nPhase 2 verified: wrote {graph_output} with {len(graph.edges)} graph edges.")


if __name__ == "__main__":
    main()
