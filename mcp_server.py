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
COMPACT_BATCH_LIMIT = 15
VALID_RESPONSE_MODES = {"full", "compact"}


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
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    records = _summary_records_for(repo, architecture, seed_records)

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


def _summary_records_for(
    repo: Path,
    architecture: dict[str, Any],
    seed_records: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = {
        node_id: record
        for node_id, record in (seed_records or {}).items()
        if isinstance(record, dict) and record.get("summary") is not None
    }
    records.update(_summary_records_from_disk(repo))
    nodes = architecture.get("nodes", {})

    for node_id, record in records.items():
        if node_id in nodes:
            record["stale"] = _summary_stale(record, nodes[node_id], nodes)
            record.pop("missing_node", None)
        else:
            record["stale"] = True
            record["missing_node"] = True
    return records


def _summary_index_payload(repo: Path, architecture: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "repo_summary": architecture.get("repo_summary"),
        "summaries": _summary_records_for(repo, architecture),
    }


def _read_models(repo: Path) -> dict[str, Any]:
    payload = _read_json(_models_path(repo), {"models": {}})
    if not isinstance(payload, dict):
        return {"models": {}}
    models = payload.get("models")
    if not isinstance(models, dict):
        payload["models"] = {}
    return payload


def _architecture_fingerprint(architecture: dict[str, Any]) -> str:
    nodes = architecture.get("nodes", {})
    payload = {
        "root": architecture.get("root"),
        "nodes": [
            {
                "id": node_id,
                "type": node.get("type"),
                "path": node.get("path"),
                "name": node.get("name"),
                "hash": node.get("hash"),
                "children": node.get("children", []),
            }
            for node_id, node in sorted(nodes.items())
        ],
        "edges": [
            {
                "type": edge.get("type"),
                "source": edge.get("source"),
                "target": edge.get("target"),
                "import_text": edge.get("import_text"),
            }
            for edge in sorted(
                architecture.get("edges", []),
                key=lambda item: (
                    item.get("source", ""),
                    item.get("target", ""),
                    item.get("type", ""),
                    item.get("import_text", ""),
                ),
            )
        ],
        "components": [
            {
                "id": component.get("id"),
                "name": component.get("name"),
                "files": sorted(component.get("files", [])),
            }
            for component in sorted(architecture.get("components", []), key=lambda item: item.get("id", ""))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    normalized["source_graph_hash"] = _architecture_fingerprint(architecture)
    payload = _read_models(repo)
    payload["generated_at"] = _utc_now()
    payload.setdefault("models", {})[model_type] = normalized
    _models_path(repo).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_static_viewer(repo, architecture)
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


def _summary_targets(
    repo: Path,
    architecture: dict[str, Any],
    records: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    current_records = records if records is not None else _summary_records_for(repo, architecture)
    return {
        "structure": _structure_summary_targets(architecture, current_records),
        "architecture": _architecture_summary_targets(architecture, current_records),
        "runtime": _runtime_summary_targets(architecture, current_records),
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
        "Call get_context_batch(path=path) or get_summary_context_bundle(path=path), write grounded "
        "host-LLM summaries, then call save_summaries(items, path)."
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


def _context_for_node(
    repo: Path,
    architecture: dict[str, Any],
    node_id: str,
    include_source: bool = True,
) -> dict[str, Any]:
    nodes = architecture.get("nodes", {})
    node = nodes.get(node_id)
    if node is None:
        return {"error": f"Node not found: {node_id}", "node_id": node_id}

    if node.get("type") == "repo":
        context = _repo_context(repo, architecture, node, nodes)
    elif node.get("type") == "folder":
        context = _folder_context(repo, architecture, node, nodes)
    elif node.get("type") == "component":
        context = _component_context(repo, architecture, node, nodes)
    else:
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

        context = {
            "node": node,
            "file": file_node,
            "source": source,
            "symbols": children,
            "edges": related_edge_ids,
            "neighbors": neighbors,
            "saved_summary": None if saved_summary.get("missing") else saved_summary,
        }

    source_chars = len(context.get("source") or "")
    source_count = len(context.get("sources") or [])
    context["context_stats"] = {
        "source_included": include_source,
        "source_chars": source_chars if include_source else 0,
        "source_chars_available": source_chars,
        "sources_count": source_count,
        "symbols_count": len(context.get("symbols") or []),
        "edges_count": len(context.get("edges") or []),
        "file_edges_count": len(context.get("file_edges") or []),
        "neighbors_count": len(context.get("neighbors") or []),
    }
    if include_source:
        return context

    stripped_sources = []
    for item in context.get("sources") or []:
        if isinstance(item, dict):
            stripped_sources.append(
                {
                    key: value
                    for key, value in item.items()
                    if key != "source"
                }
            )
    return {
        **context,
        "source": "",
        "sources": stripped_sources,
    }


def _limited_node_ids(node_ids: list[str] | None, worklist: list[dict[str, Any]], limit: int | None) -> tuple[list[str], dict[str, Any]]:
    requested = node_ids or [item["node_id"] for item in worklist if item.get("node_id")]
    normalized_limit = None if limit is None or limit < 0 else limit
    selected = requested[:normalized_limit] if normalized_limit is not None else requested
    return selected, {
        "requested": len(requested),
        "returned": len(selected),
        "limit": normalized_limit,
        "truncated": normalized_limit is not None and len(requested) > normalized_limit,
        "remaining_after_limit": max(0, len(requested) - len(selected)),
        "defaulted_to_worklist": not node_ids,
        "worklist_total": len(worklist),
    }


def _response_mode(value: str) -> str:
    if value not in VALID_RESPONSE_MODES:
        return "full"
    return value


def _model_refinement_status(repo: Path, architecture: dict[str, Any]) -> dict[str, Any]:
    models = _read_models(repo).get("models", {})
    source_graph_hash = _architecture_fingerprint(architecture)
    architecture_model = models.get("architecture")
    runtime_model = models.get("runtime")
    has_architecture = isinstance(architecture_model, dict)
    has_runtime = isinstance(runtime_model, dict)
    architecture_current = has_architecture and architecture_model.get("source_graph_hash") == source_graph_hash
    runtime_current = has_runtime and runtime_model.get("source_graph_hash") == source_graph_hash
    return {
        "source": "local_candidates_need_host_refinement",
        "source_graph_hash": source_graph_hash,
        "architecture_required": not architecture_current,
        "runtime_required": not runtime_current,
        "complete": architecture_current and runtime_current,
        "saved_models": {
            "architecture": has_architecture,
            "runtime": has_runtime,
        },
        "current_models": {
            "architecture": architecture_current,
            "runtime": runtime_current,
        },
        "stale_models": {
            "architecture": has_architecture and not architecture_current,
            "runtime": has_runtime and not runtime_current,
        },
        "local_candidates": {
            "architecture_components": len(architecture.get("components", [])),
            "runtime_dependency_edges": len(architecture.get("edges", [])),
        },
        "required_action": (
            "After summaries are current, use get_map and get_context to write or refresh grounded architecture "
            "and runtime/input-flow models, then call save_architecture_model and save_runtime_model."
        ),
        "note": (
            "Structure is the concrete scanned graph. Architecture and Runtime are local static candidates "
            "until current host-refined models are saved."
        ),
    }


def _model_seed(repo: Path) -> dict[str, Any]:
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    nodes = architecture.get("nodes", {})
    files = [node for node in nodes.values() if node.get("type") == "file"]
    symbol_types = {"function", "class", "interface", "struct", "type"}
    symbols = [node for node in nodes.values() if node.get("type") in symbol_types]
    entrypoint_names = {
        "__init__.py",
        "aksi.py",
        "app.py",
        "cli.py",
        "index.js",
        "index.ts",
        "index.tsx",
        "main.py",
        "main.ts",
        "main.tsx",
        "mcp_server.py",
        "server.py",
        "server.ts",
        "server.tsx",
    }
    entrypoints = [
        {
            "id": node.get("id"),
            "name": node.get("name"),
            "path": node.get("path"),
            "language": node.get("language"),
            "stale": bool(node.get("stale")),
            "unused_hint": bool(node.get("unused")),
        }
        for node in sorted(files, key=lambda item: item.get("path", ""))
        if Path(str(node.get("path", ""))).name in entrypoint_names
        or str(node.get("path", "")).startswith(("tests/", "test/"))
    ]
    if not entrypoints and files:
        first_file = sorted(files, key=lambda item: item.get("path", ""))[0]
        entrypoints.append(
            {
                "id": first_file.get("id"),
                "name": first_file.get("name"),
                "path": first_file.get("path"),
                "language": first_file.get("language"),
                "stale": bool(first_file.get("stale")),
                "unused_hint": bool(first_file.get("unused")),
                "note": "Fallback candidate because no conventional entrypoint name was found.",
            }
        )
    key_files = [
        {
            "id": node.get("id"),
            "name": node.get("name"),
            "path": node.get("path"),
            "language": node.get("language"),
            "incoming_local_imports": node.get("usage_count", 0),
            "outgoing_local_imports": node.get("outgoing_usage_count", 0),
            "stale": bool(node.get("stale")),
            "unused_hint": bool(node.get("unused")),
        }
        for node in sorted(
            files,
            key=lambda item: (
                -int(item.get("usage_count") or 0),
                -int(item.get("outgoing_usage_count") or 0),
                item.get("path", ""),
            ),
        )[:25]
    ]

    architecture_components = []
    for component in sorted(architecture.get("components", []), key=lambda item: item.get("name", "")):
        architecture_components.append(
            {
                "id": component.get("id"),
                "name": component.get("name"),
                "role": component.get("role"),
                "detail": component.get("detail"),
                "why": component.get("why"),
                "how": component.get("how"),
                "files": component.get("files", []),
                "file_count": component.get("file_count", 0),
                "symbol_count": component.get("symbol_count", 0),
                "import_count": component.get("import_count", 0),
                "stale": bool(component.get("stale")),
                "unused_hint": bool(component.get("unused")),
            }
        )

    def endpoint(edge: dict[str, Any], key: str) -> dict[str, Any]:
        node = nodes.get(edge.get(key, ""), {})
        return {
            "id": edge.get(key),
            "name": node.get("name") or edge.get(key),
            "type": node.get("type"),
            "path": node.get("path"),
        }

    component_edges = [
        {
            "id": edge.get("id"),
            "type": edge.get("type"),
            "source": endpoint(edge, "source"),
            "target": endpoint(edge, "target"),
            "import_text": edge.get("import_text"),
            "examples": edge.get("examples", []),
            "count": edge.get("count", 1),
        }
        for edge in architecture.get("component_edges", [])
    ]
    dependency_edges = [
        {
            "id": edge.get("id"),
            "type": edge.get("type"),
            "source": endpoint(edge, "source"),
            "target": endpoint(edge, "target"),
            "import_text": edge.get("import_text"),
            "module": edge.get("module"),
            "is_external": str(edge.get("target", "")).startswith("external:"),
        }
        for edge in architecture.get("edges", [])[:80]
    ]
    external_dependencies = sorted(
        {
            nodes[edge.get("target", "")].get("name")
            for edge in architecture.get("edges", [])
            if str(edge.get("target", "")).startswith("external:") and edge.get("target", "") in nodes
        }
    )
    stale_files = [
        {"id": node.get("id"), "path": node.get("path")}
        for node in sorted(files, key=lambda item: item.get("path", ""))
        if node.get("stale")
    ]
    unused_files = [
        {"id": node.get("id"), "path": node.get("path"), "reason": node.get("dead_reason")}
        for node in sorted(files, key=lambda item: item.get("path", ""))
        if node.get("unused")
    ]
    unused_symbols = [
        {
            "id": node.get("id"),
            "name": node.get("name"),
            "path": node.get("path"),
            "start_line": node.get("start_line"),
            "reason": node.get("dead_reason"),
        }
        for node in sorted(symbols, key=lambda item: (item.get("path", ""), item.get("start_line", 0)))
        if node.get("unused")
    ][:80]
    model_refinement = _model_refinement_status(repo, architecture)
    summary_targets = _summary_targets(repo, architecture)
    summary_worklist = _summary_worklist(summary_targets)
    summary_completion = _summary_completion(summary_worklist)
    if not summary_completion["complete"]:
        suggested_next = {
            "action": "summarize_batch",
            "tool": "get_summary_context_bundle",
            "reason": "Summaries must be current before refined models complete the workflow.",
        }
    elif not model_refinement["complete"]:
        suggested_next = {
            "action": "refine_models",
            "tool": "get_model_seed",
            "reason": "Use this seed plus get_context/get_context_batch evidence to save required refined models.",
        }
    else:
        suggested_next = {
            "action": "release_viewer",
            "tool": "get_workflow_status",
            "reason": "Workflow is complete; get_workflow_status returns the viewer link.",
        }
    return {
        "path": str(repo),
        "source": "local_seed_for_host_llm_refinement",
        "llm_called_by_aksi": False,
        "source_graph_hash": model_refinement["source_graph_hash"],
        "repo": {
            "name": nodes.get(architecture.get("root", ""), {}).get("name") or repo.name,
            "summary": architecture.get("repo_summary"),
            "counts": summarize_architecture(architecture),
            "scanner": architecture.get("scanner", {}),
            "generated_at": architecture.get("generated_at"),
        },
        "entrypoints": entrypoints,
        "key_files": key_files,
        "model_refinement": model_refinement,
        "summary_completion": summary_completion,
        "summary_worklist_remaining": len(summary_worklist),
        "suggested_next": suggested_next,
        "architecture_seed": {
            "components": architecture_components,
            "component_edges": component_edges,
            "entrypoints": entrypoints,
            "instruction": (
                "Host LLM should turn these local component candidates into a concise project architecture model. "
                "Keep only supported components and mark uncertainty."
            ),
        },
        "runtime_seed": {
            "kind": "static_dependency_flow_seed",
            "entrypoints": entrypoints,
            "dependency_edges": dependency_edges,
            "external_dependencies": external_dependencies,
            "unresolved_externals": external_dependencies,
            "truncated_dependency_edges": max(0, len(architecture.get("edges", [])) - len(dependency_edges)),
            "instruction": (
                "Host LLM should infer a cautious input/data flow only from dependency edges and context evidence. "
                "Do not claim traced runtime execution unless source context proves it."
            ),
        },
        "risk_hints": {
            "stale_files": stale_files,
            "unused_files": unused_files,
            "unused_symbols": unused_symbols,
            "unused_note": architecture.get("analysis", {}).get("note"),
        },
        "required_context": {
            "repo_root": architecture.get("root"),
            "entrypoints": [item["id"] for item in entrypoints if item.get("id")],
            "components": [item["id"] for item in architecture_components if item.get("id")],
            "recommended_tool": "get_context_batch",
        },
        "model_shape": {
            "nodes": "Non-empty list of {id, name, type, summary/detail, confidence, evidence_node_ids}.",
            "edges": "List of {source, target, type, label/detail, evidence_edge_ids}; endpoints must reference model node ids.",
        },
    }


def _workflow_status(
    repo: Path,
    limit: int | None = None,
    prepare_summary_targets: bool = True,
    response_mode: str = "full",
) -> dict[str, Any]:
    mode = _response_mode(response_mode)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    summary_targets = _summary_targets(repo, architecture) if prepare_summary_targets else _empty_summary_targets()
    summary_worklist = _summary_worklist(summary_targets)
    summary_counts = _summary_status(summary_targets, summary_worklist)
    summary_completion = _summary_completion(summary_worklist)
    model_refinement = _model_refinement_status(repo, architecture)
    effective_limit = COMPACT_BATCH_LIMIT if mode == "compact" and limit is None else limit
    selected_ids, batch_limits = _limited_node_ids(None, summary_worklist, effective_limit)

    worklist_missing = sum(1 for item in summary_worklist if item.get("summary_status") == "missing")
    worklist_stale = sum(1 for item in summary_worklist if item.get("summary_status") == "stale")
    summaries_complete = bool(summary_completion["complete"])
    models_complete = bool(model_refinement["complete"])
    releasable = summaries_complete and models_complete

    if not summaries_complete:
        next_action = "summarize_batch"
        withheld_reason = f"summary_worklist has {len(summary_worklist)} remaining items."
        instructions = [
            "Call get_summary_context_bundle(path=path, limit=limit) for recommended_batch.node_ids.",
            "Write and verify one grounded summary per returned context.",
            "Call save_summaries(items, path=path) once for the batch.",
            "Call get_workflow_status(path=path, limit=limit) again.",
        ]
    elif not models_complete:
        next_action = "refine_models"
        required_models = [
            name
            for name, required in (
                ("architecture", model_refinement["architecture_required"]),
                ("runtime", model_refinement["runtime_required"]),
            )
            if required
        ]
        withheld_reason = f"model_refinement is incomplete; required models: {', '.join(required_models)}."
        instructions = [
            "Call get_model_seed(path=path) for compact architecture/runtime candidates and risk hints.",
            "Call get_map(path=path) and relevant get_context_batch/get_context calls for any evidence that needs source detail.",
            "Build only the required architecture/runtime models from returned map and context data.",
            "Call save_architecture_model(model, path=path) and/or save_runtime_model(model, path=path).",
            "Call get_workflow_status(path=path, limit=limit) again.",
        ]
    else:
        next_action = "release_viewer"
        withheld_reason = None
        instructions = [
            "Use viewer_http_url when present, otherwise use viewer_url.",
            "Share the viewer link with the user.",
        ]

    viewer_status: dict[str, Any] = {
        "releasable": releasable,
        "withheld": not releasable,
        "withheld_reason": withheld_reason,
    }
    if releasable:
        viewer_file = _viewer_path(repo)
        viewer_status["viewer_url"] = viewer_file.as_uri()
        try:
            viewer_status["viewer_http_url"] = _viewer_http_url(repo)
            viewer_status["viewer_http_error"] = None
        except OSError as error:
            viewer_status["viewer_http_url"] = None
            viewer_status["viewer_http_error"] = str(error)

    result = {
        "path": str(repo),
        "response_mode": mode,
        "next_action": next_action,
        "summary": {
            "complete": summaries_complete,
            "required": bool(summary_completion["required"]),
            "mode": "host_llm_worklist" if prepare_summary_targets else "disabled",
            "remaining": len(summary_worklist),
            "missing": worklist_missing,
            "stale": worklist_stale,
            "target_counts": summary_counts,
        },
        "summary_worklist": summary_worklist,
        "recommended_batch": {
            "tool": "get_summary_context_bundle" if summary_worklist else None,
            "fallback_tool": "get_context_batch" if summary_worklist else None,
            "node_ids": selected_ids,
            "limit": batch_limits["limit"],
            "remaining_after_limit": batch_limits["remaining_after_limit"],
            "truncated": batch_limits["truncated"],
            "call": "get_summary_context_bundle(path=path, limit=limit)" if summary_worklist else None,
        },
        "model": {
            "complete": models_complete,
            "architecture_required": model_refinement["architecture_required"],
            "runtime_required": model_refinement["runtime_required"],
            "current_models": model_refinement["current_models"],
            "stale_models": model_refinement["stale_models"],
            "saved_models": model_refinement["saved_models"],
            "source_graph_hash": model_refinement["source_graph_hash"],
            "seed_tool": "get_model_seed" if not models_complete else None,
        },
        "viewer": viewer_status,
        "instructions": instructions,
    }
    if mode == "compact":
        result.pop("summary_worklist", None)
        result["summary"]["work_items"] = len(summary_worklist)
        result["summary"]["worklist_omitted"] = True
        result["summary"]["worklist_tool"] = "get_summary_worklist"
    return result


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
    response_mode: str = "full",
) -> dict[str, Any]:
    """Generate the architecture map for UI/MCP use without requiring users to run aksi.py."""
    repo = _repo(path)
    mode = _response_mode(response_mode)
    should_prepare_summaries = summarize if prepare_summary_targets is None else prepare_summary_targets
    preserved_summary_records = _summary_records_from_disk(repo)
    result, architecture = _scan_repository(repo, preserved_summary_records)
    architecture = refresh_stale_flags(architecture, repo)
    summary_targets = _summary_targets(repo, architecture) if should_prepare_summaries else _empty_summary_targets()
    summary_worklist = _summary_worklist(summary_targets)
    summary_status = _summary_status(summary_targets, summary_worklist)
    summary_completion = _summary_completion(summary_worklist)
    model_refinement = _model_refinement_status(repo, architecture)
    viewer_file = _write_static_viewer(repo, architecture)
    summaries_ready = summary_completion["complete"] or not should_prepare_summaries
    workflow_complete = summaries_ready and bool(model_refinement["complete"])
    viewer_http_url = None
    viewer_http_error = None
    viewer_url = viewer_file.as_uri() if workflow_complete else None
    if serve_viewer and workflow_complete:
        try:
            viewer_http_url = _viewer_http_url(repo)
        except OSError as error:
            viewer_http_error = str(error)
    elif not workflow_complete:
        viewer_http_error = "withheld_until_summary_and_model_refinement_complete"
    full_result = {
        **result,
        "response_mode": mode,
        "viewer_file": str(viewer_file),
        "viewer_url": viewer_url,
        "viewer_http_url": viewer_http_url,
        "viewer_http_error": viewer_http_error,
        "viewer_release": {
            "complete": workflow_complete,
            "withheld": not workflow_complete,
            "reason": None
            if workflow_complete
            else "summary_worklist and model_refinement must be complete before returning a viewer URL.",
        },
        "summary_index_file": str(_summary_index_path(repo)),
        "summary_targets": summary_targets,
        "summary_worklist": summary_worklist,
        "summary_status": summary_status,
        "summary_completion": summary_completion,
        "summaries_complete": summary_completion["complete"],
        "model_refinement": model_refinement,
        "summary_mode": "host_llm_worklist" if should_prepare_summaries else "disabled",
        "summary_behavior": {
            "automatic_summaries": False,
            "written_by_aksi": 0,
            "parameter_note": "summarize/prepare_summary_targets prepares host-LLM work items; it does not call an LLM or write summaries.",
        },
        "host_llm_required": bool(summary_worklist),
        "summary_workflow": [
            "bundle = get_summary_context_bundle(path)",
            "summary_worklist = bundle['summary_worklist']",
            "for item in bundle['items']:",
            "    summary = host_llm_write_summary(item['context'])",
            "    verify_summary_matches_context(summary, item['context'])",
            "save_summaries(items, path)",
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
            "Complete summary_worklist first; summaries and model refinement are separate loops.",
            "Call get_map(path) and get_context(node_id, path) for repo root and important files/components.",
            "Host LLM may refine labels and grouping only from grounded get_map/get_context evidence.",
            "Host LLM should call get_model_seed(path) first for compact local Architecture/Runtime candidates.",
            "Host LLM calls save_architecture_model(model, path) for an optional grounded architecture model.",
            "Host LLM calls save_runtime_model(model, path) for an optional grounded runtime/input-flow model.",
            "Refined models do not clear summary_worklist; only save_summaries/save_summary clears summary work.",
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
            "If summary_completion.required is true, call get_context_batch or get_summary_context_bundle for summary_worklist items and write grounded host-LLM summaries.",
            "Verify each summary matches the exact get_context node, path, type, source, edges, neighbors, and context limits; re-summarize mismatches before saving.",
            "Call save_summaries for verified explanations, or save_summary for a single targeted explanation, then re-check completion with get_summary_worklist or generate_visualization.",
            "Only say saved rectangle summaries are current when summary_mode is host_llm_worklist and refreshed summary_completion.complete is true.",
            "If summary_mode is disabled, say the graph is ready without summary targets.",
            "After summaries are current, inspect model_refinement; if architecture_required or runtime_required is true, call get_model_seed, then write grounded refined models from seed/map/context evidence.",
            "viewer_http_url and viewer_url are withheld until summaries and required model refinement are complete; do not stop at viewer_file.",
            "Use save_architecture_model and save_runtime_model only for optional grounded refinements; they do not clear summary_worklist.",
        ],
    }
    if mode == "compact":
        workflow = _workflow_status(
            repo,
            prepare_summary_targets=should_prepare_summaries,
            response_mode="compact",
        )
        return {
            "path": str(repo),
            "response_mode": mode,
            "summary": result["summary"],
            "architecture_file": result["architecture_file"],
            "viewer_file": str(viewer_file),
            "summary_index_file": str(_summary_index_path(repo)),
            "viewer_url": viewer_url,
            "viewer_http_url": viewer_http_url,
            "viewer_http_error": viewer_http_error,
            "viewer_release": full_result["viewer_release"],
            "summary_mode": full_result["summary_mode"],
            "summary_status": summary_status,
            "summary_completion": summary_completion,
            "summaries_complete": summary_completion["complete"],
            "model_refinement": model_refinement,
            "host_llm_required": bool(summary_worklist),
            "next_action": workflow["next_action"],
            "recommended_batch": workflow["recommended_batch"],
            "instructions": workflow["instructions"],
            "omitted": {
                "summary_targets": True,
                "summary_worklist": True,
                "summary_schema": True,
                "refinement_workflow": True,
                "refined_model_schema": True,
                "next_steps": True,
            },
        }
    return full_result


@mcp.tool
def get_map(path: str = ".") -> dict[str, Any]:
    """Return the current architecture map, refreshing stale flags from disk."""
    repo = _repo(path)
    architecture = load_architecture(repo)
    return refresh_stale_flags(architecture, repo)


@mcp.tool
def get_summary_worklist(path: str = ".") -> dict[str, Any]:
    """Return the deduplicated host-LLM summary worklist without rescanning."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
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
def get_workflow_status(
    path: str = ".",
    limit: int | None = None,
    prepare_summary_targets: bool = True,
    response_mode: str = "full",
) -> dict[str, Any]:
    """Return the next Aksi workflow action without requiring agents to interpret raw status fields."""
    return _workflow_status(
        _repo(path),
        limit=limit,
        prepare_summary_targets=prepare_summary_targets,
        response_mode=response_mode,
    )


@mcp.tool
def get_model_seed(path: str = ".") -> dict[str, Any]:
    """Return compact local facts that help the host LLM refine Architecture and Runtime models."""
    return _model_seed(_repo(path))


@mcp.tool
def get_context(node_id: str, path: str = ".") -> dict[str, Any]:
    """Return source code and neighbor metadata for a node."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    return _context_for_node(repo, architecture, node_id)


@mcp.tool
def get_context_batch(
    node_ids: list[str] | None = None,
    path: str = ".",
    limit: int | None = None,
    include_source: bool = True,
) -> dict[str, Any]:
    """Return context for many summary nodes, defaulting to the missing/stale worklist."""
    repo = _repo(path)
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    summary_targets = _summary_targets(repo, architecture)
    worklist = _summary_worklist(summary_targets)
    selected_ids, batch_limits = _limited_node_ids(node_ids, worklist, limit)
    contexts: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for node_id in selected_ids:
        context = _context_for_node(repo, architecture, node_id, include_source=include_source)
        if context.get("error"):
            error = {"node_id": node_id, "error": context["error"]}
            errors.append(error)
            items.append(error)
            continue
        contexts[node_id] = context
        items.append({"node_id": node_id, "context": context})

    return {
        "path": str(repo),
        "contexts": contexts,
        "items": items,
        "errors": errors,
        "batch": {
            **batch_limits,
            "include_source": include_source,
            "successes": len(contexts),
            "errors": len(errors),
        },
        "summary_worklist": worklist,
        "summary_completion": _summary_completion(worklist),
    }


@mcp.tool
def get_summary_context_bundle(path: str = ".", limit: int | None = None, include_source: bool = True) -> dict[str, Any]:
    """Return the current summary worklist and matching contexts in one call."""
    return get_context_batch(node_ids=None, path=path, limit=limit, include_source=include_source)


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
def save_summaries(items: list[dict[str, Any]], path: str = ".") -> dict[str, Any]:
    """Persist many LLM-written summaries and refresh the summary index/viewer once."""
    repo = _repo(path)
    results: list[dict[str, Any]] = []
    saved_records: dict[str, Any] = {}
    saved_count = 0

    if not isinstance(items, list):
        return {"error": "items must be a list of {node_id, summary} objects", "path": str(repo)}

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            results.append({"index": index, "saved": False, "error": "item must be an object"})
            continue
        node_id = item.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            results.append({"index": index, "saved": False, "error": "item.node_id must be a non-empty string"})
            continue
        if "summary" not in item:
            results.append({"index": index, "node_id": node_id, "saved": False, "error": "item.summary is required"})
            continue
        try:
            saved = _save_summary_record(repo, node_id, item["summary"], "llm_host")
        except KeyError:
            results.append({"index": index, "node_id": node_id, "saved": False, "error": f"Node not found: {node_id}"})
            continue
        except TypeError as error:
            results.append(
                {
                    "index": index,
                    "node_id": node_id,
                    "saved": False,
                    "error": f"Summary is not JSON serializable: {error}",
                }
            )
            continue
        saved_records[node_id] = saved["record"]
        saved_count += 1
        results.append({"index": index, "node_id": node_id, **saved})

    if saved_records:
        _write_summary_index(repo, saved_records)
        _write_static_viewer(repo, refresh_stale_flags(load_architecture(repo), repo))

    worklist_state = get_summary_worklist(str(repo))
    failures = [result for result in results if not result.get("saved")]
    return {
        "path": str(repo),
        "saved": saved_count,
        "failed": len(failures),
        "results": results,
        "errors": failures,
        "summary_completion": worklist_state["summary_completion"],
        "summary_worklist": worklist_state["summary_worklist"],
        "summaries_complete": worklist_state["summaries_complete"],
    }


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
    architecture = refresh_stale_flags(load_architecture(repo), repo)
    return _summary_index_payload(repo, architecture)


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
