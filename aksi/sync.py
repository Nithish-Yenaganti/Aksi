from __future__ import annotations

import argparse
import json
import shelve
import time
from pathlib import Path
from typing import Any

from .hash import file_sha256
from .io import read_json


def refresh_stale_state(
    symbols_path: Path = Path("Files/symbols.json"),
    graph_path: Path = Path("Files/index.json"),
) -> dict[str, Any]:
    symbols = read_json(symbols_path)
    graph = read_json(graph_path)
    root = Path(str(symbols["root"]))
    stale_by_path: dict[str, bool] = {}
    stale_files: list[str] = []

    for file_record in symbols.get("files", []):
        relative_path = str(file_record["path"])
        current_path = root / relative_path
        stale = not current_path.exists() or file_sha256(current_path) != file_record.get("sha256")
        file_record["stale"] = stale
        stale_by_path[relative_path] = stale
        if stale:
            stale_files.append(relative_path)

    _mark_graph_stale(graph.get("tree", {}), stale_by_path)
    _write_json(symbols_path, symbols)
    _write_json(graph_path, graph)

    return {
        "symbols_path": str(symbols_path),
        "graph_path": str(graph_path),
        "stale_count": len(stale_files),
        "stale_files": stale_files,
    }


def build_metadata_cache(
    symbols_path: Path = Path("Files/symbols.json"),
    cache_path: Path = Path("Files/metadata_cache"),
) -> dict[str, Any]:
    symbols = read_json(symbols_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    symbol_count = 0
    with shelve.open(str(cache_path)) as cache:
        cache.clear()
        cache["root"] = symbols.get("root")
        cache["generated_at"] = symbols.get("generated_at")
        cache["files"] = {file["path"]: file for file in symbols.get("files", [])}
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for file_record in symbols.get("files", []):
            for symbol in file_record.get("symbols", []):
                symbol_count += 1
                by_symbol.setdefault(str(symbol["name"]).lower(), []).append(
                    {
                        "path": file_record["path"],
                        "language": file_record["language"],
                        "symbol": symbol,
                    }
                )
        cache["symbols"] = by_symbol

    return {
        "cache_path": str(cache_path),
        "files": len(symbols.get("files", [])),
        "symbols": symbol_count,
    }


def watch_repo(
    symbols_path: Path = Path("Files/symbols.json"),
    graph_path: Path = Path("Files/index.json"),
    cache_path: Path = Path("Files/metadata_cache"),
    interval: float = 1.0,
) -> None:
    symbols = read_json(symbols_path)
    root = Path(str(symbols["root"]))
    print(f"Watching {root} for Aksi stale-state updates.")

    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        _poll_watch(symbols_path, graph_path, cache_path, interval)
        return

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: Any) -> None:
            if event.is_directory:
                return
            result = refresh_stale_state(symbols_path, graph_path)
            build_metadata_cache(symbols_path, cache_path)
            print(f"Sync updated: {result['stale_count']} stale file(s).")

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nAksi sync watcher stopped.")
    finally:
        observer.stop()
        observer.join()


def _poll_watch(
    symbols_path: Path,
    graph_path: Path,
    cache_path: Path,
    interval: float,
) -> None:
    last_seen: dict[str, float] = {}
    while True:
        symbols = read_json(symbols_path)
        root = Path(str(symbols["root"]))
        current = {
            str(file["path"]): (root / str(file["path"])).stat().st_mtime
            for file in symbols.get("files", [])
            if (root / str(file["path"])).exists()
        }
        if current != last_seen:
            result = refresh_stale_state(symbols_path, graph_path)
            build_metadata_cache(symbols_path, cache_path)
            print(f"Sync updated: {result['stale_count']} stale file(s).")
            last_seen = current
        time.sleep(interval)


def _mark_graph_stale(node: dict[str, Any], stale_by_path: dict[str, bool]) -> bool:
    children = node.get("children", [])
    child_stale = any(_mark_graph_stale(child, stale_by_path) for child in children)
    own_stale = bool(stale_by_path.get(str(node.get("path")), False)) if node.get("kind") == "file" else False
    node["stale"] = own_stale or child_stale
    return bool(node["stale"])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh or watch Aksi stale-state artifacts.")
    parser.add_argument("--symbols", type=Path, default=Path("Files/symbols.json"))
    parser.add_argument("--graph", type=Path, default=Path("Files/index.json"))
    parser.add_argument("--cache", type=Path, default=Path("Files/metadata_cache"))
    parser.add_argument("--watch", action="store_true", help="Continuously watch for file changes.")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval when watchdog is unavailable.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.watch:
        watch_repo(args.symbols, args.graph, args.cache, args.interval)
        return
    result = refresh_stale_state(args.symbols, args.graph)
    cache = build_metadata_cache(args.symbols, args.cache)
    print(f"Stale files: {result['stale_count']}; cache symbols: {cache['symbols']}")


if __name__ == "__main__":
    main()
