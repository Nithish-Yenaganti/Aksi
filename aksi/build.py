from __future__ import annotations

import argparse
from pathlib import Path

from .graph import build_project_graph, write_graph
from .scanner import scan_repo, write_symbols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Aksi symbol and graph artifacts for a repository.")
    parser.add_argument("repo", type=Path, help="Repository root to scan.")
    parser.add_argument(
        "--symbols-out",
        type=Path,
        default=Path("Files/symbols.json"),
        help="Output symbols.json path.",
    )
    parser.add_argument(
        "--graph-out",
        type=Path,
        default=Path("Files/index.json"),
        help="Output graph index.json path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    index = scan_repo(args.repo)
    graph = build_project_graph(index)
    write_symbols(index, args.symbols_out)
    write_graph(graph, args.graph_out)
    print(
        f"Wrote {len(index.files)} files and {len(graph.edges)} edges "
        f"to {args.symbols_out} and {args.graph_out}"
    )


if __name__ == "__main__":
    main()
