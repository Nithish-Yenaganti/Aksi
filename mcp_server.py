"""FastMCP bridge for Aksi."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from graph import load_architecture, refresh_stale_flags, slug, summarize_architecture, write_architecture

mcp = FastMCP("Aksi")


def _repo(path: str = ".") -> Path:
    return Path(path).expanduser().resolve()


def _context_dir(repo: Path) -> Path:
    path = repo / "Files" / "context"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _summary_path(repo: Path, node_id: str) -> Path:
    return _context_dir(repo) / f"{slug(node_id)}.json"


def _summary_index_path(repo: Path) -> Path:
    return _context_dir(repo) / "index.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_node_for(node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if node.get("type") == "file":
        return node
    file_path = node.get("path")
    return next(
        (
            candidate
            for candidate in nodes.values()
            if candidate.get("type") == "file" and candidate.get("path") == file_path
        ),
        node,
    )


def _node_and_file(repo: Path, node_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})
    node = nodes.get(node_id)
    if node is None:
        raise KeyError(node_id)
    return architecture, node, _file_node_for(node, nodes)


def _summary_stale(record: dict[str, Any], file_node: dict[str, Any]) -> bool:
    saved_hash = record.get("file_hash")
    current_hash = file_node.get("hash")
    return bool(file_node.get("stale")) or bool(saved_hash and current_hash and saved_hash != current_hash)


def _read_summary_record(repo: Path, node_id: str) -> dict[str, Any] | None:
    path = _summary_path(repo, node_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_summary_index(repo: Path) -> None:
    context_dir = _context_dir(repo)
    records: dict[str, Any] = {}
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})

    for path in sorted(context_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        node_id = record.get("node_id")
        if not node_id or node_id not in nodes:
            continue
        file_node = _file_node_for(nodes[node_id], nodes)
        record["stale"] = _summary_stale(record, file_node)
        records[node_id] = record

    _summary_index_path(repo).write_text(
        json.dumps({"generated_at": _utc_now(), "summaries": records}, indent=2),
        encoding="utf-8",
    )


@mcp.tool
def scan_repo(path: str = ".") -> dict[str, Any]:
    """Scan a repository and write Files/architecture.json."""
    architecture = write_architecture(_repo(path))
    _write_summary_index(_repo(path))
    return {
        "path": str(_repo(path)),
        "summary": summarize_architecture(architecture),
        "architecture_file": str(_repo(path) / "Files" / "architecture.json"),
    }


@mcp.tool
def generate_visualization(path: str = ".") -> dict[str, Any]:
    """Generate the architecture map for UI/MCP use without requiring users to run aksi.py."""
    repo = _repo(path)
    result = scan_repo(str(repo))
    return {
        **result,
        "ui_file": str(repo / "ui" / "index.html"),
        "summary_index_file": str(_summary_index_path(repo)),
        "next_steps": [
            "Call get_map to inspect the generated graph.",
            "Call get_context for exact source before writing an LLM summary.",
            "Call save_summary to persist the LLM-written explanation for future use.",
        ],
    }


@mcp.tool
def get_map(path: str = ".") -> dict[str, Any]:
    """Return the current architecture map, refreshing stale flags from disk."""
    repo = _repo(path)
    architecture = load_architecture(repo)
    _write_summary_index(repo)
    return refresh_stale_flags(architecture, repo)


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
    file_node = _file_node_for(node, nodes)

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
    saved_summary = get_summary(node_id, str(repo))

    return {
        "node": node,
        "file": file_node,
        "source": source,
        "symbols": children,
        "edges": related_edge_ids,
        "neighbors": neighbors,
        "saved_summary": None if saved_summary.get("missing") else saved_summary,
    }


@mcp.tool
def save_summary(node_id: str, summary: Any, path: str = ".") -> dict[str, Any]:
    """Persist an LLM-written summary for a node using the current file hash."""
    repo = _repo(path)
    try:
        _architecture, node, file_node = _node_and_file(repo, node_id)
    except KeyError:
        return {"error": f"Node not found: {node_id}", "node_id": node_id}

    existing = _read_summary_record(repo, node_id) or {}
    now = _utc_now()
    record = {
        "node_id": node_id,
        "name": node.get("name"),
        "type": node.get("type"),
        "path": node.get("path"),
        "file_hash": file_node.get("hash"),
        "summary": summary,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "stale": False,
        "written_by": "llm_host",
    }
    output_path = _summary_path(repo, node_id)
    output_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    _write_summary_index(repo)
    return {"saved": True, "summary_file": str(output_path), "record": record}


@mcp.tool
def get_summary(node_id: str, path: str = ".") -> dict[str, Any]:
    """Return a saved node summary and whether it is stale."""
    repo = _repo(path)
    record = _read_summary_record(repo, node_id)
    if record is None:
        return {"missing": True, "node_id": node_id}

    try:
        _architecture, _node, file_node = _node_and_file(repo, node_id)
    except KeyError:
        return {**record, "stale": True, "missing_node": True}

    record["stale"] = _summary_stale(record, file_node)
    return record


@mcp.tool
def list_summaries(path: str = ".") -> dict[str, Any]:
    """List saved summaries for the repository."""
    repo = _repo(path)
    _write_summary_index(repo)
    index_path = _summary_index_path(repo)
    return json.loads(index_path.read_text(encoding="utf-8"))


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
