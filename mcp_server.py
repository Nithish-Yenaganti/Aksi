"""FastMCP bridge for Aksi."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from graph import load_architecture, refresh_stale_flags, summarize_architecture, write_architecture

mcp = FastMCP("Aksi")


def _repo(path: str = ".") -> Path:
    return Path(path).expanduser().resolve()


@mcp.tool
def scan_repo(path: str = ".") -> dict[str, Any]:
    """Scan a repository and write Files/architecture.json."""
    architecture = write_architecture(_repo(path))
    return {
        "path": str(_repo(path)),
        "summary": summarize_architecture(architecture),
        "architecture_file": str(_repo(path) / "Files" / "architecture.json"),
    }


@mcp.tool
def get_map(path: str = ".") -> dict[str, Any]:
    """Return the current architecture map, refreshing stale flags from disk."""
    architecture = load_architecture(_repo(path))
    return refresh_stale_flags(architecture, _repo(path))


@mcp.tool
def get_context(node_id: str, path: str = ".") -> dict[str, Any]:
    """Return source code and neighbor metadata for a node."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})
    node = nodes.get(node_id)
    if node is None:
        return {"error": f"Node not found: {node_id}", "node_id": node_id}

    file_path = node.get("path")
    file_node = node
    if node.get("type") != "file":
        file_node = next(
            (
                candidate
                for candidate in nodes.values()
                if candidate.get("type") == "file" and candidate.get("path") == file_path
            ),
            node,
        )

    source = ""
    if file_path:
        source_path = repo / file_path
        if source_path.exists() and source_path.is_file():
            source = source_path.read_text(encoding="utf-8", errors="replace")

    related_edge_ids = [
        edge
        for edge in architecture.get("edges", [])
        if edge.get("source") == file_node.get("id") or edge.get("target") == file_node.get("id")
    ]
    neighbor_ids = sorted(
        {
            endpoint
            for edge in related_edge_ids
            for endpoint in (edge.get("source"), edge.get("target"))
            if endpoint and endpoint != file_node.get("id")
        }
    )
    neighbors = [nodes[item] for item in neighbor_ids if item in nodes]
    children = [nodes[item] for item in file_node.get("children", []) if item in nodes]

    return {
        "node": node,
        "file": file_node,
        "source": source,
        "symbols": children,
        "edges": related_edge_ids,
        "neighbors": neighbors,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
