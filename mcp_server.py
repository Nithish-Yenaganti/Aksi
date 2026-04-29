"""FastMCP bridge for Aksi."""

from __future__ import annotations

import functools
import hashlib
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
MAX_COMPONENT_CONTEXT_FILES = 12


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


def _models_path(repo: Path) -> Path:
    return _context_dir(repo) / "models.json"


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


def _stop_viewer_server(repo: Path) -> bool:
    server_info = _VIEWER_SERVERS.pop(str(repo), None)
    if server_info is None:
        return False
    server, _port = server_info
    server.shutdown()
    server.server_close()
    return True


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
    models = _read_json(_models_path(repo), {"models": {}})
    marker = "  <script>\n    const svg = d3.select"
    embedded = (
        "  <script>\n"
        f"    window.__AKSI_ARCHITECTURE__ = {_script_json(architecture)};\n"
        f"    window.__AKSI_SUMMARIES__ = {_script_json(summaries)};\n"
        f"    window.__AKSI_MODELS__ = {_script_json(models)};\n"
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


def _context_hash_for_node(node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> str | None:
    node_type = node.get("type")
    if node_type == "file":
        return node.get("hash")
    if node_type in {"function", "class", "interface", "struct", "type"}:
        return _file_node_for(node, nodes).get("hash")
    if node_type == "external":
        return None

    file_nodes: list[dict[str, Any]]
    if node_type == "repo":
        file_nodes = [candidate for candidate in nodes.values() if candidate.get("type") == "file"]
    elif node_type in {"folder", "component"}:
        file_nodes = _descendant_file_nodes(node, nodes)
    else:
        file_nodes = []

    hashes = sorted(
        f"{file_node.get('path', '')}:{file_node.get('hash', '')}"
        for file_node in file_nodes
        if file_node.get("hash")
    )
    if not hashes:
        return None
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


def _summary_stale(record: dict[str, Any], node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> bool:
    file_node = _file_node_for(node, nodes)
    if node.get("stale") or file_node.get("stale"):
        return True

    saved_context_hash = record.get("context_hash")
    current_context_hash = _context_hash_for_node(node, nodes)
    if saved_context_hash and current_context_hash:
        return saved_context_hash != current_context_hash

    saved_hash = record.get("file_hash")
    current_hash = file_node.get("hash")
    return bool(saved_hash and current_hash and saved_hash != current_hash)


def _read_source(repo: Path, relpath: str) -> str:
    source_path = repo / relpath
    if not source_path.exists() or not source_path.is_file():
        return ""
    try:
        return source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _component_context(
    repo: Path,
    architecture: dict[str, Any],
    node: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    file_ids = [item for item in node.get("children", []) if nodes.get(item, {}).get("type") == "file"]
    files = [nodes[item] for item in file_ids if item in nodes]
    included_files = files[:MAX_COMPONENT_CONTEXT_FILES]
    omitted_files = max(0, len(files) - len(included_files))
    sources = [{"path": file_node.get("path"), "source": _read_source(repo, file_node.get("path", ""))} for file_node in included_files]
    source = "\n\n".join(f"# {item['path']}\n{item['source']}" for item in sources if item.get("path"))
    symbols = [
        nodes[child]
        for file_node in files
        for child in file_node.get("children", [])
        if child in nodes
    ]
    component_edges = [
        edge
        for edge in architecture.get("component_edges", [])
        if edge.get("source") == node.get("id") or edge.get("target") == node.get("id")
    ]
    neighbor_ids = sorted(
        {
            endpoint
            for edge in component_edges
            for endpoint in (edge.get("source"), edge.get("target"))
            if endpoint and endpoint != node.get("id")
        }
    )
    file_edge_ids = set(file_ids)
    file_edges = [
        edge
        for edge in architecture.get("edges", [])
        if edge.get("source") in file_edge_ids or edge.get("target") in file_edge_ids
    ]
    saved_summary = get_summary(node["id"], str(repo))
    return {
        "node": node,
        "file": node,
        "source": source,
        "sources": sources,
        "symbols": symbols,
        "edges": component_edges,
        "file_edges": file_edges,
        "neighbors": [nodes[item] for item in neighbor_ids if item in nodes],
        "context_limit": {
            "included_files": len(included_files),
            "omitted_files": omitted_files,
            "max_component_context_files": MAX_COMPONENT_CONTEXT_FILES,
        },
        "saved_summary": None if saved_summary.get("missing") else saved_summary,
    }


def _descendant_file_nodes(node: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    stack = list(node.get("children", []))
    seen: set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        child = nodes.get(node_id)
        if not child:
            continue
        if child.get("type") == "file":
            files.append(child)
            continue
        stack.extend(child.get("children", []))
    return sorted(files, key=lambda item: item.get("path", ""))


def _folder_context(
    repo: Path,
    architecture: dict[str, Any],
    node: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    files = _descendant_file_nodes(node, nodes)
    sources = [{"path": file_node.get("path"), "source": _read_source(repo, file_node.get("path", ""))} for file_node in files[:12]]
    source = "\n\n".join(f"# {item['path']}\n{item['source']}" for item in sources if item.get("path"))
    file_ids = {file_node.get("id") for file_node in files}
    file_edges = [
        edge
        for edge in architecture.get("edges", [])
        if edge.get("source") in file_ids or edge.get("target") in file_ids
    ]
    symbols = [
        nodes[child]
        for file_node in files
        for child in file_node.get("children", [])
        if child in nodes
    ]
    saved_summary = get_summary(node["id"], str(repo))
    return {
        "node": node,
        "file": node,
        "source": source,
        "sources": sources,
        "symbols": symbols,
        "edges": [],
        "file_edges": file_edges,
        "neighbors": files,
        "saved_summary": None if saved_summary.get("missing") else saved_summary,
    }


def _repo_context(
    repo: Path,
    architecture: dict[str, Any],
    node: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    components = architecture.get("components", [])
    saved_summary = get_summary(node["id"], str(repo))
    return {
        "node": {
            **node,
            "detail": architecture.get("repo_summary"),
            "files": [component.get("name") for component in components],
        },
        "file": node,
        "source": "",
        "sources": [],
        "symbols": [],
        "edges": architecture.get("component_edges", []),
        "file_edges": architecture.get("edges", [])[:40],
        "neighbors": [nodes[component["id"]] for component in components if component.get("id") in nodes],
        "saved_summary": None if saved_summary.get("missing") else saved_summary,
    }


def _read_summary_record(repo: Path, node_id: str) -> dict[str, Any] | None:
    path = _summary_path(repo, node_id)
    record = _read_json(path, None)
    if isinstance(record, dict):
        return record

    index = _read_json(_summary_index_path(repo), {})
    indexed_record = (index.get("summaries") or {}).get(node_id)
    if not isinstance(indexed_record, dict):
        return None
    indexed_record["node_id"] = indexed_record.get("node_id") or node_id
    return indexed_record


def _summary_records_from_disk(repo: Path) -> dict[str, Any]:
    context_dir = _context_dir(repo)
    records: dict[str, Any] = {}
    old_index = _read_json(_summary_index_path(repo), {})

    for node_id, record in (old_index.get("summaries") or {}).items():
        if isinstance(record, dict) and record.get("summary") is not None:
            record["node_id"] = record.get("node_id") or node_id
            records[node_id] = record

    for path in sorted(context_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        record = _read_json(path, None)
        if not isinstance(record, dict):
            continue
        node_id = record.get("node_id")
        if not node_id:
            continue
        records[node_id] = record
    return records


def _write_summary_index(repo: Path, seed_records: dict[str, Any] | None = None) -> None:
    records = {
        node_id: record
        for node_id, record in (seed_records or {}).items()
        if isinstance(record, dict) and record.get("summary") is not None
    }
    records.update(_summary_records_from_disk(repo))
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})

    for node_id, record in records.items():
        if node_id in nodes:
            record["stale"] = _summary_stale(record, nodes[node_id], nodes)
            record.pop("missing_node", None)
        else:
            record["stale"] = True
            record["missing_node"] = True

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


def _read_models(repo: Path) -> dict[str, Any]:
    payload = _read_json(_models_path(repo), {"models": {}})
    if not isinstance(payload, dict):
        return {"models": {}}
    models = payload.get("models")
    if not isinstance(models, dict):
        payload["models"] = {}
    return payload


def _validate_refined_model(model: Any, model_type: str) -> dict[str, Any]:
    if not isinstance(model, dict):
        raise TypeError("model must be a JSON object")
    nodes = model.get("nodes")
    edges = model.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("model.nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise ValueError("model.edges must be a list")

    normalized_nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for index, node in enumerate(nodes, start=1):
        if not isinstance(node, dict):
            raise ValueError("each model node must be an object")
        node_id = str(node.get("id") or f"{model_type}:{index}")
        name = str(node.get("name") or node_id)
        normalized = {
            **node,
            "id": node_id,
            "name": name,
            "type": node.get("type") or model_type,
        }
        node_ids.add(node_id)
        normalized_nodes.append(normalized)

    normalized_edges: list[dict[str, Any]] = []
    for index, edge in enumerate(edges, start=1):
        if not isinstance(edge, dict):
            raise ValueError("each model edge must be an object")
        source = edge.get("source")
        target = edge.get("target")
        if source not in node_ids or target not in node_ids:
            raise ValueError("model edge endpoints must reference model node ids")
        normalized_edges.append(
            {
                **edge,
                "id": edge.get("id") or f"{model_type}-edge:{index}",
                "type": edge.get("type") or "refined_relationship",
                "source": source,
                "target": target,
            }
        )

    return {
        **model,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "model_type": model_type,
        "updated_at": _utc_now(),
        "written_by": "llm_host",
    }


def _save_refined_model(repo: Path, model_type: str, model: Any) -> dict[str, Any]:
    normalized = _validate_refined_model(model, model_type)
    payload = _read_models(repo)
    payload["generated_at"] = _utc_now()
    payload.setdefault("models", {})[model_type] = normalized
    _models_path(repo).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_static_viewer(repo, refresh_stale_flags(load_architecture(repo), repo))
    return {"saved": True, "model_type": model_type, "models_file": str(_models_path(repo)), "model": normalized}


def _save_summary_record(repo: Path, node_id: str, summary: Any, written_by: str) -> dict[str, Any]:
    _architecture, node, file_node = _node_and_file(repo, node_id)
    existing = _read_summary_record(repo, node_id) or {}
    now = _utc_now()
    record = {
        "node_id": node_id,
        "name": node.get("name"),
        "type": node.get("type"),
        "path": node.get("path"),
        "file_hash": file_node.get("hash"),
        "context_hash": _context_hash_for_node(node, _architecture.get("nodes", {})),
        "summary": summary,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "stale": False,
        "written_by": written_by,
    }
    output_path = _summary_path(repo, node_id)
    output_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"saved": True, "summary_file": str(output_path), "record": record}


def _target_record(
    node: dict[str, Any],
    view: str,
    reason: str,
    priority: int,
    records: dict[str, Any],
) -> dict[str, Any]:
    record = records.get(node.get("id"))
    status = "missing"
    if record:
        status = "stale" if record.get("stale") else "fresh"
    return {
        "node_id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
        "path": node.get("path"),
        "view": view,
        "reason": reason,
        "priority": priority,
        "summary_status": status,
        "needs_summary": status in {"missing", "stale"},
        "action": "write" if status == "missing" else "refresh" if status == "stale" else "skip",
    }


def _structure_summary_targets(architecture: dict[str, Any], records: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = architecture.get("nodes", {})
    targets: list[dict[str, Any]] = []
    root = nodes.get(architecture.get("root", ""))
    if root:
        targets.append(_target_record(root, "structure", "repo structure summary", 0, records))

    priority_by_type = {
        "folder": 20,
        "file": 30,
        "class": 40,
        "interface": 40,
        "struct": 40,
        "type": 40,
        "function": 50,
    }
    for node in sorted(nodes.values(), key=lambda item: (item.get("path", ""), item.get("name", ""))):
        node_type = node.get("type")
        if node_type not in priority_by_type:
            continue
        reason = f"{node_type} structure summary"
        if node.get("unused"):
            reason = f"possibly unused {node_type} summary"
        if node.get("stale"):
            reason = f"stale {node_type} summary"
        targets.append(_target_record(node, "structure", reason, priority_by_type[node_type], records))
    return targets


def _architecture_summary_targets(architecture: dict[str, Any], records: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = architecture.get("nodes", {})
    targets: list[dict[str, Any]] = []
    for component in architecture.get("components", []):
        node = nodes.get(component.get("id"))
        if not node:
            continue
        targets.append(_target_record(node, "architecture", "architecture component summary", 10, records))
    return targets


def _runtime_summary_targets(architecture: dict[str, Any], records: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = architecture.get("nodes", {})
    runtime_ids = {
        node.get("id")
        for node in nodes.values()
        if node.get("type") == "file"
    }
    runtime_ids.update(
        endpoint
        for edge in architecture.get("edges", [])
        for endpoint in (edge.get("source"), edge.get("target"))
        if endpoint in nodes and nodes[endpoint].get("type") == "external"
    )
    targets: list[dict[str, Any]] = []
    for node_id in sorted(runtime_ids):
        node = nodes[node_id]
        reason = "runtime dependency endpoint" if node.get("type") == "external" else "runtime flow module"
        targets.append(_target_record(node, "runtime", reason, 20 if node.get("type") == "file" else 60, records))
    return targets


def _summary_targets(repo: Path, architecture: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    records = (_read_json(_summary_index_path(repo), {}).get("summaries") or {})
    return {
        "structure": _structure_summary_targets(architecture, records),
        "architecture": _architecture_summary_targets(architecture, records),
        "runtime": _runtime_summary_targets(architecture, records),
    }


def _empty_summary_targets() -> dict[str, list[dict[str, Any]]]:
    return {"structure": [], "architecture": [], "runtime": []}


def _summary_worklist(summary_targets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    work_by_node: dict[str, dict[str, Any]] = {}
    for view, targets in summary_targets.items():
        for target in targets:
            if not target.get("needs_summary"):
                continue
            node_id = target.get("node_id")
            if not node_id:
                continue
            if node_id not in work_by_node:
                work_by_node[node_id] = {
                    **target,
                    "views": [view],
                    "reasons": [target.get("reason")],
                }
            else:
                work = work_by_node[node_id]
                work["views"].append(view)
                work["reasons"].append(target.get("reason"))
                work["priority"] = min(work.get("priority", 999), target.get("priority", 999))
                if work.get("summary_status") != "stale" and target.get("summary_status") == "stale":
                    work["summary_status"] = "stale"
                    work["action"] = "refresh"
    return sorted(work_by_node.values(), key=lambda item: (item.get("priority", 999), item.get("node_id", "")))


def _summary_status(summary_targets: dict[str, list[dict[str, Any]]], worklist: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {"fresh": 0, "missing": 0, "stale": 0}
    by_view: dict[str, dict[str, int]] = {}
    for view, targets in summary_targets.items():
        view_counts = {"fresh": 0, "missing": 0, "stale": 0}
        for target in targets:
            status = target.get("summary_status")
            if status in status_counts:
                status_counts[status] += 1
                view_counts[status] += 1
        by_view[view] = {
            **view_counts,
            "total": len(targets),
            "needs_summary": sum(1 for target in targets if target.get("needs_summary")),
        }
    return {
        **status_counts,
        "total_targets": sum(len(targets) for targets in summary_targets.values()),
        "work_items": len(worklist),
        "by_view": by_view,
    }


def _summary_completion(worklist: list[dict[str, Any]]) -> dict[str, Any]:
    remaining = len(worklist)
    required_action = (
        "For every summary_worklist item, call get_context(node_id, path), write a grounded host-LLM "
        "summary, then call save_summary(node_id, summary, path)."
    )
    return {
        "complete": remaining == 0,
        "required": remaining > 0,
        "remaining": remaining,
        "viewer_state": "graph_ready_summaries_pending" if remaining else "graph_ready_summaries_current",
        "required_action": required_action if remaining else "No host summary work is currently required.",
        "note": (
            "The viewer can show the graph before summaries are complete, but rectangle explanations "
            "only become grounded after save_summary updates Files/context/index.json."
        ),
    }


def _scan_repository(
    repo: Path,
    preserved_summary_records: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    architecture = write_architecture(repo)
    _write_summary_index(repo, preserved_summary_records)
    result = {
        "path": str(repo),
        "summary": summarize_architecture(architecture),
        "architecture_file": str(repo / "Files" / "architecture.json"),
    }
    return result, architecture


@mcp.tool
def scan_repo(path: str = ".") -> dict[str, Any]:
    """Scan a repository and write Files/architecture.json."""
    repo = _repo(path)
    result, _architecture = _scan_repository(repo)
    return result


@mcp.tool
def generate_visualization(
    path: str = ".",
    summarize: bool = True,
    prepare_summary_targets: bool | None = None,
    serve_viewer: bool = True,
) -> dict[str, Any]:
    """Generate the architecture map for UI/MCP use without requiring users to run aksi.py."""
    repo = _repo(path)
    should_prepare_summaries = summarize if prepare_summary_targets is None else prepare_summary_targets
    preserved_summary_records = _summary_records_from_disk(repo)
    result, architecture = _scan_repository(repo, preserved_summary_records)
    architecture = refresh_stale_flags(architecture, repo)
    summary_targets = _summary_targets(repo, architecture) if should_prepare_summaries else _empty_summary_targets()
    summary_worklist = _summary_worklist(summary_targets)
    summary_status = _summary_status(summary_targets, summary_worklist)
    summary_completion = _summary_completion(summary_worklist)
    viewer_file = _write_static_viewer(repo, architecture)
    viewer_http_url = None
    viewer_http_error = None
    if serve_viewer:
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
        "summary_targets": summary_targets,
        "summary_worklist": summary_worklist,
        "summary_status": summary_status,
        "summary_completion": summary_completion,
        "summaries_complete": summary_completion["complete"],
        "summary_mode": "host_llm_worklist" if should_prepare_summaries else "disabled",
        "summary_behavior": {
            "automatic_summaries": False,
            "written_by_aksi": 0,
            "parameter_note": "summarize/prepare_summary_targets prepares host-LLM work items; it does not call an LLM or write summaries.",
        },
        "host_llm_required": bool(summary_worklist),
        "summary_workflow": [
            "for target in summary_worklist:",
            "    context = get_context(target['node_id'], path)",
            "    summary = host_llm_write_summary(context)",
            "    save_summary(target['node_id'], summary, path)",
        ],
        "summary_schema": {
            "purpose": "What this node is for in one sentence.",
            "behavior": "What it actually does, grounded in get_context output.",
            "interfaces": "Important functions, classes, inputs, outputs, commands, or MCP tools exposed here.",
            "dependencies": "Key upstream/downstream files, modules, services, or data it relies on.",
            "used_by": "Known callers, views, workflows, or project areas that depend on it.",
            "change_risk": "low, medium, or high, with the reason a future agent should care.",
            "open_questions": "Important unknowns or cases where the source should be reopened.",
            "confidence": "high, medium, or low based on how complete the returned context was.",
        },
        "refinement_workflow": [
            "Use local Architecture and Runtime Flow as candidates only.",
            "Call get_map(path) and get_context(node_id, path) for repo root and important files/components.",
            "Host LLM may refine labels and grouping only from grounded get_map/get_context evidence.",
            "Host LLM calls save_architecture_model(model, path) for an optional grounded architecture model.",
            "Host LLM calls save_runtime_model(model, path) for an optional grounded runtime/input-flow model.",
            "Refined models do not clear summary_worklist; only save_summary clears summary work.",
            "Mark uncertainty and do not add unsupported components, flows, callers, dependencies, or runtime behavior.",
            "Aksi regenerates Files/index.html and the viewer prefers saved host-refined models.",
        ],
        "refined_model_schema": {
            "nodes": [
                {
                    "id": "stable id",
                    "name": "display name",
                    "type": "architecture_component or runtime_step",
                    "purpose": "short explanation",
                    "behavior": "grounded behavior",
                    "interfaces": "important exposed surfaces",
                    "dependencies": "important connected pieces",
                    "used_by": "known consumers",
                    "change_risk": "low, medium, or high",
                    "open_questions": "what future agents should verify",
                    "confidence": "high, medium, or low",
                }
            ],
            "edges": [{"source": "node id", "target": "node id", "label": "relationship"}],
        },
        "next_steps": [
            "Inspect summary_mode, summary_completion, and summary_worklist before presenting the viewer as complete.",
            "Treat summary_worklist as the executable queue; do not iterate summary_targets directly for required work.",
            "If summary_completion.required is true, call get_context for every summary_worklist item and write grounded host-LLM summaries.",
            "Call save_summary for each written explanation, then re-check completion with get_summary_worklist or generate_visualization.",
            "Only say saved rectangle summaries are current when summary_mode is host_llm_worklist and refreshed summary_completion.complete is true.",
            "If summary_mode is disabled, say the graph is ready without summary targets.",
            "Give viewer_http_url when present; otherwise give viewer_url, labeling early links as graph-only previews when summaries remain pending.",
            "Use save_architecture_model and save_runtime_model only for optional grounded refinements; they do not clear summary_worklist.",
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
def get_summary_worklist(path: str = ".") -> dict[str, Any]:
    """Return the deduplicated host-LLM summary worklist without rescanning."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    _write_summary_index(repo)
    summary_targets = _summary_targets(repo, architecture)
    worklist = _summary_worklist(summary_targets)
    completion = _summary_completion(worklist)
    return {
        "path": str(repo),
        "summary_targets": summary_targets,
        "summary_worklist": worklist,
        "summary_status": _summary_status(summary_targets, worklist),
        "summary_completion": completion,
        "summaries_complete": completion["complete"],
        "host_llm_required": bool(worklist),
    }


@mcp.tool
def get_context(node_id: str, path: str = ".") -> dict[str, Any]:
    """Return source code and neighbor metadata for a node."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})
    node = nodes.get(node_id)
    if node is None:
        return {"error": f"Node not found: {node_id}", "node_id": node_id}

    if node.get("type") == "repo":
        return _repo_context(repo, architecture, node, nodes)

    if node.get("type") == "folder":
        return _folder_context(repo, architecture, node, nodes)

    if node.get("type") == "component":
        return _component_context(repo, architecture, node, nodes)

    file_path = node.get("path")
    file_node = _file_node_for(node, nodes)

    source = _read_source(repo, file_path) if file_path else ""

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
        saved = _save_summary_record(repo, node_id, summary, "llm_host")
    except KeyError:
        return {"error": f"Node not found: {node_id}", "node_id": node_id}
    except TypeError as error:
        return {"error": f"Summary is not JSON serializable: {error}", "node_id": node_id}
    _write_summary_index(repo)
    _write_static_viewer(repo, refresh_stale_flags(load_architecture(repo), repo))
    return saved


@mcp.tool
def get_summary(node_id: str, path: str = ".") -> dict[str, Any]:
    """Return a saved node summary and whether it is stale."""
    repo = _repo(path)
    record = _read_summary_record(repo, node_id)
    if record is None:
        return {"missing": True, "node_id": node_id}

    try:
        _architecture, _node, _file_node = _node_and_file(repo, node_id)
    except KeyError:
        return {**record, "stale": True, "missing_node": True}

    record["stale"] = _summary_stale(record, _node, _architecture.get("nodes", {}))
    return record


@mcp.tool
def list_summaries(path: str = ".") -> dict[str, Any]:
    """List saved summaries for the repository."""
    repo = _repo(path)
    _write_summary_index(repo)
    _write_static_viewer(repo, refresh_stale_flags(load_architecture(repo), repo))
    index_path = _summary_index_path(repo)
    return json.loads(index_path.read_text(encoding="utf-8"))


@mcp.tool
def save_architecture_model(model: dict[str, Any], path: str = ".") -> dict[str, Any]:
    """Persist a host-LLM refined project architecture model for the viewer."""
    repo = _repo(path)
    try:
        return _save_refined_model(repo, "architecture", model)
    except (TypeError, ValueError) as error:
        return {"error": str(error), "model_type": "architecture"}


@mcp.tool
def save_runtime_model(model: dict[str, Any], path: str = ".") -> dict[str, Any]:
    """Persist a host-LLM refined runtime/input-flow model for the viewer."""
    repo = _repo(path)
    try:
        return _save_refined_model(repo, "runtime", model)
    except (TypeError, ValueError) as error:
        return {"error": str(error), "model_type": "runtime"}


@mcp.tool
def get_models(path: str = ".") -> dict[str, Any]:
    """Return saved host-refined architecture and runtime models."""
    repo = _repo(path)
    return _read_models(repo)


@mcp.tool
def stop_viewer(path: str = ".") -> dict[str, Any]:
    """Stop the local viewer server for a repository if one is running."""
    repo = _repo(path)
    stopped = _stop_viewer_server(repo)
    return {"path": str(repo), "stopped": stopped}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
