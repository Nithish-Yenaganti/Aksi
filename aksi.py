"""Aksi ignition CLI: scan a repo, build artifacts, and serve the local map."""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path
from typing import Any

from src.engine.context import build_context_artifacts
from src.engine.graph import build_graph
from src.engine.scanner import DEFAULT_EXCLUDES, SUPPORTED_EXTENSIONS, scan_repo
from src.web.app import DEFAULT_STATIC_DIR, serve_stdlib


def build_all(repo: Path, files_dir: Path) -> dict[str, Any]:
    files_dir.mkdir(parents=True, exist_ok=True)
    symbols_path = files_dir / "symbols.json"
    graph_path = files_dir / "graph.json"
    context_dir = files_dir / "context"

    index = scan_repo(repo, symbols_path)
    graph = build_graph(symbols_path, graph_path)
    context = build_context_artifacts(symbols_path, graph_path, context_dir)
    return {
        "repo": str(repo.resolve()),
        "symbols": str(symbols_path),
        "graph": str(graph_path),
        "context": str(context_dir),
        "files": len(index.files),
        "edges": len(graph.edges),
        "context_artifacts": context["artifacts"],
        "parser_backend": index.parser_backend,
    }


def start_rescan_watcher(repo: Path, files_dir: Path, interval: float) -> threading.Thread:
    thread = threading.Thread(target=_watch_loop, args=(repo.resolve(), files_dir.resolve(), interval), daemon=True)
    thread.start()
    return thread


def _watch_loop(repo: Path, files_dir: Path, interval: float) -> None:
    snapshot = _repo_snapshot(repo)
    while True:
        time.sleep(interval)
        current = _repo_snapshot(repo)
        if current == snapshot:
            continue
        result = build_all(repo, files_dir)
        print(f"Aksi rebuilt: {result['files']} file(s), {result['edges']} edge(s).")
        snapshot = current


def _repo_snapshot(repo: Path) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in sorted(repo.rglob("*")):
        if not _tracked_source(path, repo):
            continue
        stat = path.stat()
        snapshot[path.relative_to(repo).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def _tracked_source(path: Path, repo: Path) -> bool:
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    return not any(part in DEFAULT_EXCLUDES for part in path.relative_to(repo).parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and serve an Aksi cognitive map.")
    parser.add_argument("repo", nargs="?", type=Path, default=Path.cwd(), help="Repository to scan. Defaults to the current directory.")
    parser.add_argument("--files", type=Path, default=Path("Files"), help="Directory for generated Aksi artifacts.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--watch", action="store_true", help="Rebuild artifacts when tracked source files change.")
    parser.add_argument("--interval", type=float, default=1.0, help="Watcher polling interval in seconds.")
    parser.add_argument("--no-serve", action="store_true", help="Only build artifacts; do not start the local map server.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = build_all(args.repo, args.files)
    print(
        "Aksi built: "
        f"{result['files']} file(s), {result['edges']} edge(s), "
        f"{result['context_artifacts']} context artifact(s) using {result['parser_backend']}."
    )
    if args.no_serve:
        return
    if args.watch:
        start_rescan_watcher(args.repo, args.files, args.interval)
        print("Aksi watcher: rebuild-on-change is active.")
    serve_stdlib(args.files, args.host, args.port, DEFAULT_STATIC_DIR)


if __name__ == "__main__":
    main()
