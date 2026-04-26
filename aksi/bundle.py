from __future__ import annotations

import argparse
from pathlib import Path

from .graph import build_project_graph, write_graph
from .scanner import scan_repo, write_symbols
from .sync import build_metadata_cache, refresh_stale_state
from .visualizer import write_standalone_bundle, write_visualization


def bundle_repo(repo: Path, output_dir: Path = Path("Files")) -> dict[str, str | int]:
    index = scan_repo(repo)
    graph = build_project_graph(index)
    symbols_path = output_dir / "symbols.json"
    graph_path = output_dir / "index.json"
    write_symbols(index, symbols_path)
    write_graph(graph, graph_path)
    html_path = write_visualization(output_dir)
    bundle_path = write_standalone_bundle(graph_path, output_dir / "aksi_bundle.html")
    sync_result = refresh_stale_state(symbols_path, graph_path)
    cache_result = build_metadata_cache(symbols_path, output_dir / "metadata_cache")
    return {
        "repo": str(repo.resolve()),
        "symbols_path": str(symbols_path),
        "graph_path": str(graph_path),
        "html_path": str(html_path),
        "bundle_path": str(bundle_path),
        "metadata_cache": str(output_dir / "metadata_cache"),
        "files": len(index.files),
        "edges": len(graph.edges),
        "stale_count": int(sync_result["stale_count"]),
        "cached_symbols": int(cache_result["symbols"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a complete Aksi artifact bundle.")
    parser.add_argument("repo", type=Path, help="Repository root to bundle.")
    parser.add_argument("--out", type=Path, default=Path("Files"), help="Output artifact directory.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = bundle_repo(args.repo, args.out)
    print(
        f"Bundled {result['files']} files, {result['edges']} edges, "
        f"{result['cached_symbols']} symbols to {result['bundle_path']}"
    )


if __name__ == "__main__":
    main()
