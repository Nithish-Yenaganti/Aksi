"""Phase 3 FastMCP bridge: expose scanner, symbol search, and file context tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.engine.graph import build_graph
from src.engine.scanner import file_sha256, scan_repo as run_scanner

DEFAULT_OUTPUT_DIR = Path("Files")


def scan_repo(repo_path: str, output_dir: str = str(DEFAULT_OUTPUT_DIR)) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    output = Path(output_dir)
    symbols_path = output / "symbols.json"
    graph_path = output / "graph.json"

    index = run_scanner(repo, symbols_path)
    graph = build_graph(symbols_path, graph_path)

    return {
        "repo": str(repo),
        "symbols_path": str(symbols_path),
        "graph_path": str(graph_path),
        "files": len(index.files),
        "edges": len(graph.edges),
        "parser_backend": index.parser_backend,
    }


def search_symbols(query: str, symbols_path: str = "Files/symbols.json") -> list[dict[str, Any]]:
    needle = query.strip().lower()
    if not needle:
        return []

    symbols = _read_json(Path(symbols_path))
    matches: list[dict[str, Any]] = []
    for file_record in symbols.get("files", []):
        hits: list[dict[str, Any]] = []
        for symbol in [*file_record.get("functions", []), *file_record.get("classes", [])]:
            if needle in str(symbol.get("name", "")).lower():
                hits.append({"match_type": symbol.get("kind"), "record": symbol})
        for import_record in file_record.get("imports", []):
            haystack = f"{import_record.get('module', '')} {import_record.get('name', '')}".lower()
            if needle in haystack:
                hits.append({"match_type": "import", "record": import_record})
        if hits or needle in str(file_record.get("path", "")).lower():
            matches.append(
                {
                    "path": file_record.get("path"),
                    "language": file_record.get("language"),
                    "sha256": file_record.get("sha256"),
                    "hits": hits,
                }
            )
    return matches


def get_file_context(
    path: str,
    repo_path: str,
    symbols_path: str = "Files/symbols.json",
    graph_path: str = "Files/graph.json",
) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    target = _safe_repo_path(repo, path)
    relative = target.relative_to(repo).as_posix()

    symbols = _read_json(Path(symbols_path))
    graph = _read_json(Path(graph_path))
    file_record = _find_file_record(symbols, relative)
    if file_record is None:
        raise FileNotFoundError(f"File is not present in symbols index: {relative}")

    current_hash = file_sha256(target)
    incoming = [edge for edge in graph.get("edges", []) if edge.get("target_path") == relative]
    outgoing = [edge for edge in graph.get("edges", []) if edge.get("source_path") == relative]

    return {
        "path": relative,
        "repo": str(repo),
        "code": target.read_text(encoding="utf-8"),
        "summary": {
            "language": file_record.get("language"),
            "functions": file_record.get("functions", []),
            "classes": file_record.get("classes", []),
            "imports": file_record.get("imports", []),
            "incoming_edges": incoming,
            "outgoing_edges": outgoing,
            "indexed_sha256": file_record.get("sha256"),
            "current_sha256": current_hash,
            "stale": current_hash != file_record.get("sha256"),
        },
    }


def create_server() -> Any:
    try:
        from fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("FastMCP is not installed. Install project dependencies before running the MCP server.") from error

    mcp = FastMCP("Aksi")

    @mcp.tool
    def scan_repo_tool(repo_path: str, output_dir: str = str(DEFAULT_OUTPUT_DIR)) -> dict[str, Any]:
        return scan_repo(repo_path, output_dir)

    @mcp.tool
    def search_symbols_tool(query: str, symbols_path: str = "Files/symbols.json") -> list[dict[str, Any]]:
        return search_symbols(query, symbols_path)

    @mcp.tool
    def get_file_context_tool(
        path: str,
        repo_path: str,
        symbols_path: str = "Files/symbols.json",
        graph_path: str = "Files/graph.json",
    ) -> dict[str, Any]:
        return get_file_context(path, repo_path, symbols_path, graph_path)

    return mcp


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Aksi artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_repo_path(repo: Path, path: str) -> Path:
    target = (repo / path).resolve()
    try:
        target.relative_to(repo)
    except ValueError as error:
        raise ValueError(f"Path escapes repository root: {path}") from error
    if not target.is_file():
        raise FileNotFoundError(f"File does not exist: {target}")
    return target


def _find_file_record(symbols: dict[str, Any], path: str) -> dict[str, Any] | None:
    for file_record in symbols.get("files", []):
        if file_record.get("path") == path:
            return file_record
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Aksi FastMCP server.")
    parser.add_argument("--check", action="store_true", help="Only instantiate the server and print registered tool readiness.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = create_server()
    if args.check:
        print("Aksi FastMCP server ready.")
        return
    server.run()


if __name__ == "__main__":
    main()
