"""Phase 5 sync layer: refresh stale hash flags and optionally watch file changes."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from src.engine.scanner import file_sha256
from src.engine.io import read_json, write_json_atomic


def refresh_stale_state(symbols_path: Path = Path("Files/symbols.json"), graph_path: Path = Path("Files/graph.json")) -> dict[str, Any]:
    symbols = _read_json(symbols_path)
    graph = _read_json(graph_path)
    root = Path(str(symbols["root"]))
    stale_by_path: dict[str, bool] = {}
    stale_files: list[str] = []

    for file_record in symbols.get("files", []):
        relative = str(file_record["path"])
        disk_path = root / relative
        stale = not disk_path.exists() or file_sha256(disk_path) != file_record.get("sha256")
        file_record["stale"] = stale
        stale_by_path[relative] = stale
        if stale:
            stale_files.append(relative)

    _mark_graph_stale(graph.get("tree", {}), stale_by_path)
    _write_json(symbols_path, symbols)
    _write_json(graph_path, graph)
    return {"stale_count": len(stale_files), "stale_files": stale_files}


def watch(symbols_path: Path = Path("Files/symbols.json"), graph_path: Path = Path("Files/graph.json"), interval: float = 1.0) -> None:
    symbols = _read_json(symbols_path)
    root = Path(str(symbols["root"]))
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        _poll(symbols_path, graph_path, interval)
        return

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: Any) -> None:
            if event.is_directory:
                return
            result = refresh_stale_state(symbols_path, graph_path)
            print(f"Sync updated: {result['stale_count']} stale file(s).")

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()
    print(f"Watching {root}")
    try:
        while True:
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nAksi sync watcher stopped.")
    finally:
        observer.stop()
        observer.join()


def _poll(symbols_path: Path, graph_path: Path, interval: float) -> None:
    last_snapshot: dict[str, float] = {}
    while True:
        symbols = _read_json(symbols_path)
        root = Path(str(symbols["root"]))
        snapshot = {
            str(file["path"]): (root / str(file["path"])).stat().st_mtime
            for file in symbols.get("files", [])
            if (root / str(file["path"])).exists()
        }
        if snapshot != last_snapshot:
            result = refresh_stale_state(symbols_path, graph_path)
            print(f"Sync updated: {result['stale_count']} stale file(s).")
            last_snapshot = snapshot
        time.sleep(interval)


def _mark_graph_stale(node: dict[str, Any], stale_by_path: dict[str, bool]) -> bool:
    children = node.get("children", [])
    child_stale = any(_mark_graph_stale(child, stale_by_path) for child in children)
    own_stale = bool(stale_by_path.get(str(node.get("path")), False)) if node.get("kind") == "file" else False
    node["stale"] = own_stale or child_stale
    return bool(node["stale"])


def _read_json(path: Path) -> dict[str, Any]:
    return read_json(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    write_json_atomic(path, payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh or watch Aksi stale flags.")
    parser.add_argument("--symbols", type=Path, default=Path("Files/symbols.json"))
    parser.add_argument("--graph", type=Path, default=Path("Files/graph.json"))
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.watch:
        watch(args.symbols, args.graph, args.interval)
        return
    result = refresh_stale_state(args.symbols, args.graph)
    print(f"Stale files: {result['stale_count']}")


if __name__ == "__main__":
    main()
