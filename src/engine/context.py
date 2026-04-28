"""Context artifacts and deterministic graph answers for chat/search surfaces."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.engine.io import read_json, write_json_atomic


def build_context_artifacts(
    symbols_path: Path = Path("Files/symbols.json"),
    graph_path: Path = Path("Files/graph.json"),
    output_dir: Path = Path("Files/context"),
) -> dict[str, Any]:
    symbols = read_json(symbols_path)
    graph = read_json(graph_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    files_written = 0

    for file_record in symbols.get("files", []):
        path = str(file_record["path"])
        incoming = [edge for edge in graph.get("edges", []) if edge.get("target_path") == path]
        outgoing = [edge for edge in graph.get("edges", []) if edge.get("source_path") == path]
        file_payload = {
            "node_id": f"file:{path}",
            "path": path,
            "sha256": file_record.get("sha256"),
            "stale": bool(file_record.get("stale", False)),
            "summary": _file_summary(file_record, incoming, outgoing),
            "functions": file_record.get("functions", []),
            "classes": file_record.get("classes", []),
            "imports": file_record.get("imports", []),
            "incoming_edges": incoming,
            "outgoing_edges": outgoing,
        }
        write_json_atomic(output_dir / f"{_slug(path)}.json", file_payload)
        files_written += 1

        for function_record in file_record.get("functions", []):
            function_name = str(function_record["name"])
            function_payload = {
                "node_id": f"function:{path}:{function_name}",
                "path": path,
                "function": function_record,
                "sha256": file_record.get("sha256"),
                "stale": bool(file_record.get("stale", False)),
                "summary": _function_summary(function_name, path, outgoing),
                "outgoing_edges": outgoing,
            }
            write_json_atomic(output_dir / "functions" / f"{_slug(path)}--{_slug(function_name)}.json", function_payload)
            files_written += 1

    return {"context_dir": str(output_dir), "artifacts": files_written}


def search_graph(query: str, symbols_path: Path = Path("Files/symbols.json"), graph_path: Path = Path("Files/graph.json")) -> dict[str, Any]:
    needle = query.strip().lower()
    symbols = read_json(symbols_path)
    graph = read_json(graph_path)
    if not needle:
        return {"query": query, "matches": [], "edges": []}

    matches: list[dict[str, Any]] = []
    for file_record in symbols.get("files", []):
        file_hits = []
        for bucket in ("functions", "classes", "imports"):
            for record in file_record.get(bucket, []):
                haystack = " ".join(str(value or "") for value in record.values()).lower()
                if needle in haystack:
                    file_hits.append({"kind": bucket[:-1], "record": record})
        if file_hits or needle in str(file_record.get("path", "")).lower():
            matches.append({"path": file_record.get("path"), "language": file_record.get("language"), "hits": file_hits})

    related_paths = {match["path"] for match in matches}
    edges = [
        edge
        for edge in graph.get("edges", [])
        if edge.get("source_path") in related_paths or edge.get("target_path") in related_paths
    ]
    return {"query": query, "matches": matches, "edges": edges}


def explain_node(node_id: str, symbols_path: Path = Path("Files/symbols.json"), graph_path: Path = Path("Files/graph.json")) -> dict[str, Any]:
    symbols = read_json(symbols_path)
    graph = read_json(graph_path)
    node = _find_node(graph.get("tree", {}), node_id)
    if node is None:
        raise KeyError(f"Node not found: {node_id}")

    path = str(node.get("path") or "")
    file_record = _find_file(symbols, path) if path else None
    incoming = [edge for edge in graph.get("edges", []) if edge.get("target_path") == path]
    outgoing = [edge for edge in graph.get("edges", []) if edge.get("source_path") == path]

    if node.get("kind") == "file" and file_record:
        summary = _file_summary(file_record, incoming, outgoing)
    elif node.get("kind") == "function":
        summary = _function_summary(str(node.get("name")), path, outgoing)
    elif node.get("kind") == "class":
        summary = f"Class {node.get('name')} is defined in {path}."
    else:
        summary = f"{node.get('kind', 'node').title()} {node.get('name')} contains {len(node.get('children', []))} child node(s)."

    return {"node": node, "summary": summary, "incoming_edges": incoming, "outgoing_edges": outgoing}


def answer_question(question: str, symbols_path: Path = Path("Files/symbols.json"), graph_path: Path = Path("Files/graph.json")) -> dict[str, Any]:
    result = search_graph(question, symbols_path, graph_path)
    if not result["matches"]:
        return {
            "answer": "I could not find a matching symbol, import, or file path in the current Aksi index.",
            "matches": [],
            "edges": [],
        }

    first = result["matches"][0]
    answer = f"Found {len(result['matches'])} matching file(s). The strongest match is {first['path']}."
    if result["edges"]:
        answer += f" There are {len(result['edges'])} related dependency edge(s) connected to the result set."
    return {"answer": answer, "matches": result["matches"], "edges": result["edges"]}


def _file_summary(file_record: dict[str, Any], incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> str:
    path = file_record.get("path")
    functions = [record.get("name") for record in file_record.get("functions", [])]
    classes = [record.get("name") for record in file_record.get("classes", [])]
    parts = [f"{path} is a {file_record.get('language')} file"]
    if classes:
        parts.append(f"defines class(es): {', '.join(classes)}")
    if functions:
        parts.append(f"defines function(s): {', '.join(functions)}")
    parts.append(f"has {len(outgoing)} outgoing and {len(incoming)} incoming dependency edge(s)")
    return "; ".join(parts) + "."


def _function_summary(function_name: str, path: str, outgoing: list[dict[str, Any]]) -> str:
    related = [edge for edge in outgoing if edge.get("source_path") == path]
    if related:
        targets = ", ".join(sorted({str(edge.get("target_path")) for edge in related}))
        return f"Function {function_name} is defined in {path}; the containing file depends on {targets}."
    return f"Function {function_name} is defined in {path}; no outgoing dependency edges are recorded for its file."


def _find_node(node: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    if node.get("id") == node_id:
        return node
    for child in node.get("children", []):
        found = _find_node(child, node_id)
        if found is not None:
            return found
    return None


def _find_file(symbols: dict[str, Any], path: str) -> dict[str, Any] | None:
    for file_record in symbols.get("files", []):
        if file_record.get("path") == path:
            return file_record
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.replace("/", "__")).strip("_") or "root"
