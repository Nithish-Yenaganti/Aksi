from __future__ import annotations

import json
import shelve
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi.bundle import bundle_repo
from aksi.sync import build_metadata_cache, refresh_stale_state


def main() -> None:
    repo = Path("tests/fixtures/polyglot")
    target = repo / "web/message.js"
    original = target.read_text(encoding="utf-8")

    result = bundle_repo(repo, Path("Files"))
    assert Path(result["symbols_path"]).exists(), result
    assert Path(result["graph_path"]).exists(), result
    assert Path(result["html_path"]).exists(), result
    assert Path(result["bundle_path"]).exists(), result
    assert int(result["cached_symbols"]) >= 5, result

    bundle_html = Path(result["bundle_path"]).read_text(encoding="utf-8")
    assert "window.__AKSI_GRAPH__" in bundle_html
    assert "src/greeter.py" in bundle_html

    try:
        target.write_text(original + "\n// Phase 5 stale marker\n", encoding="utf-8")
        stale = refresh_stale_state(Path("Files/symbols.json"), Path("Files/index.json"))
        assert stale["stale_count"] == 1, stale
        assert stale["stale_files"] == ["web/message.js"], stale

        graph = json.loads(Path("Files/index.json").read_text(encoding="utf-8"))
        assert graph["tree"]["stale"] is True
        assert _find_node(graph["tree"], "file:web/message.js")["stale"] is True
    finally:
        target.write_text(original, encoding="utf-8")

    clean = refresh_stale_state(Path("Files/symbols.json"), Path("Files/index.json"))
    assert clean["stale_count"] == 0, clean
    cache = build_metadata_cache(Path("Files/symbols.json"), Path("Files/metadata_cache"))
    assert cache["files"] == 2, cache

    with shelve.open("Files/metadata_cache") as db:
        assert "files" in db
        assert "symbols" in db
        assert "buildmessage" in db["symbols"]

    print("Phase 5 verified:")
    print(f"bundle -> {result['bundle_path']}")
    print(f"cache -> {result['metadata_cache']}")
    print("stale detection -> web/message.js marked stale then clean")


def _find_node(node: dict[str, object], node_id: str) -> dict[str, object]:
    if node.get("id") == node_id:
        return node
    for child in node.get("children", []):
        found = _find_node(child, node_id)
        if found:
            return found
    return {}


if __name__ == "__main__":
    main()
