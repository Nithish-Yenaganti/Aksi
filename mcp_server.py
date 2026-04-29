"""FastMCP bridge for Aksi."""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastmcp import FastMCP

from graph import load_architecture, refresh_stale_flags, slug, summarize_architecture, write_architecture

mcp = FastMCP("Aksi")
_VIEWER_SERVERS: dict[str, tuple[socketserver.TCPServer, int]] = {}


def _aksi_root() -> Path:
    return Path(__file__).resolve().parent


def _repo(path: str = ".") -> Path:
    return Path(path).expanduser().resolve()


def _context_dir(repo: Path) -> Path:
    path = repo / "Files" / "context"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _summary_path(repo: Path, node_id: str) -> Path:
    filename = quote(node_id.strip(), safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-") or "root"
    return _context_dir(repo) / f"{filename}.json"


def _summary_index_path(repo: Path) -> Path:
    return _context_dir(repo) / "index.json"


def _viewer_path(repo: Path) -> Path:
    return repo / "Files" / "index.html"


def _viewer_http_url(repo: Path) -> str:
    key = str(repo)
    if key not in _VIEWER_SERVERS:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(repo / "Files"))
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        port = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _VIEWER_SERVERS[key] = (server, port)
    _server, port = _VIEWER_SERVERS[key]
    return f"http://127.0.0.1:{port}/index.html"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _script_json(payload: Any) -> str:
    return json.dumps(payload).replace("</", "<\\/")


def _write_static_viewer(repo: Path, architecture: dict[str, Any]) -> Path:
    ui_source = (_aksi_root() / "ui" / "index.html").read_text(encoding="utf-8")
    summaries = _read_json(_summary_index_path(repo), {"summaries": {}})
    marker = "  <script>\n    const svg = d3.select"
    embedded = (
        "  <script>\n"
        f"    window.__AKSI_ARCHITECTURE__ = {_script_json(architecture)};\n"
        f"    window.__AKSI_SUMMARIES__ = {_script_json(summaries)};\n"
        "  </script>\n"
    )
    if marker not in ui_source:
        raise RuntimeError("Could not embed architecture data into ui/index.html")
    viewer = ui_source.replace(marker, f"{embedded}{marker}", 1)
    output_path = _viewer_path(repo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(viewer, encoding="utf-8")
    return output_path


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
    record = _read_json(path, None)
    if not isinstance(record, dict):
        return None
    return record


def _write_summary_index(repo: Path) -> None:
    context_dir = _context_dir(repo)
    records: dict[str, Any] = {}
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})

    for path in sorted(context_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        record = _read_json(path, None)
        if not isinstance(record, dict):
            continue
        node_id = record.get("node_id")
        if not node_id:
            continue
        if node_id in nodes:
            file_node = _file_node_for(nodes[node_id], nodes)
            record["stale"] = _summary_stale(record, file_node)
        else:
            record["stale"] = True
            record["missing_node"] = True
        records[node_id] = record

    _summary_index_path(repo).write_text(
        json.dumps(
            {
                "generated_at": _utc_now(),
                "repo_summary": architecture.get("repo_summary"),
                "summaries": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


@mcp.tool
def scan_repo(path: str = ".") -> dict[str, Any]:
    """Scan a repository and write Files/architecture.json."""
    repo = _repo(path)
    architecture = write_architecture(repo)
    _write_summary_index(repo)
    return {
        "path": str(repo),
        "summary": summarize_architecture(architecture),
        "architecture_file": str(repo / "Files" / "architecture.json"),
    }


@mcp.tool
def generate_visualization(path: str = ".") -> dict[str, Any]:
    """Generate the architecture map for UI/MCP use without requiring users to run aksi.py."""
    repo = _repo(path)
    result = scan_repo(str(repo))
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    viewer_file = _write_static_viewer(repo, architecture)
    viewer_http_url = None
    viewer_http_error = None
    try:
        viewer_http_url = _viewer_http_url(repo)
    except OSError as error:
        viewer_http_error = str(error)
    return {
        **result,
        "viewer_file": str(viewer_file),
        "viewer_url": viewer_file.as_uri(),
        "viewer_http_url": viewer_http_url,
        "viewer_http_error": viewer_http_error,
        "summary_index_file": str(_summary_index_path(repo)),
        "next_steps": [
            "Give the user viewer_http_url when present; otherwise give viewer_url.",
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
            try:
                source = source_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                source = ""

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
    try:
        payload = json.dumps(record, indent=2)
    except TypeError as error:
        return {"error": f"Summary is not JSON serializable: {error}", "node_id": node_id}
    output_path = _summary_path(repo, node_id)
    output_path.write_text(payload, encoding="utf-8")
    _write_summary_index(repo)
    _write_static_viewer(repo, refresh_stale_flags(load_architecture(repo), repo))
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
