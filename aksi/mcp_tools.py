from __future__ import annotations

from pathlib import Path
from typing import Any

from .graph import build_project_graph, write_graph
from .hash import file_sha256
from .io import ensure_within_root, read_json
from .scanner import scan_repo as scan_repository
from .scanner import write_symbols


def scan_repo(repo_path: str, output_dir: str = "Files") -> dict[str, Any]:
    """Scan a repository and write Aksi symbol and graph artifacts."""
    repo = Path(repo_path).resolve()
    artifacts = Path(output_dir)
    index = scan_repository(repo)
    graph = build_project_graph(index)

    symbols_path = artifacts / "symbols.json"
    graph_path = artifacts / "index.json"
    write_symbols(index, symbols_path)
    write_graph(graph, graph_path)

    return {
        "repo": str(repo),
        "symbols_path": str(symbols_path),
        "graph_path": str(graph_path),
        "files": len(index.files),
        "edges": len(graph.edges),
    }


def search_symbols(query: str, symbols_path: str = "Files/symbols.json") -> list[dict[str, Any]]:
    """Search the symbols index by keyword."""
    needle = query.strip().lower()
    if not needle:
        return []

    artifact = read_json(Path(symbols_path))
    matches: list[dict[str, Any]] = []
    for file_record in artifact.get("files", []):
        for symbol in file_record.get("symbols", []):
            haystack = " ".join(
                str(value or "")
                for value in (
                    symbol.get("name"),
                    symbol.get("kind"),
                    symbol.get("signature"),
                    symbol.get("docstring"),
                    file_record.get("path"),
                    file_record.get("language"),
                )
            ).lower()
            if needle in haystack:
                matches.append(
                    {
                        "path": file_record.get("path"),
                        "language": file_record.get("language"),
                        "symbol": symbol,
                        "sha256": file_record.get("sha256"),
                        "stale": file_record.get("stale", False),
                    }
                )
    return matches


def get_context(
    path: str,
    repo_path: str,
    symbols_path: str = "Files/symbols.json",
) -> dict[str, Any]:
    """Return raw code and indexed metadata for a repository path."""
    repo = Path(repo_path).resolve()
    target = ensure_within_root(repo, repo / path)
    relative = target.relative_to(repo).as_posix()
    artifact = read_json(Path(symbols_path))

    metadata = None
    for file_record in artifact.get("files", []):
        if file_record.get("path") == relative:
            metadata = file_record
            break
    if metadata is None:
        raise FileNotFoundError(f"Path is not present in symbols index: {relative}")

    current_hash = file_sha256(target)
    indexed_hash = metadata.get("sha256")
    stale = current_hash != indexed_hash

    return {
        "path": relative,
        "repo": str(repo),
        "code": target.read_text(encoding="utf-8"),
        "metadata": {**metadata, "stale": stale},
        "current_sha256": current_hash,
        "indexed_sha256": indexed_hash,
        "stale": stale,
    }
