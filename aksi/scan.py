from __future__ import annotations

import argparse
from pathlib import Path

from .scanner import scan_repo, write_symbols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a repository into an Aksi symbols.json index.")
    parser.add_argument("repo", type=Path, help="Repository root to scan.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("Files/symbols.json"),
        help="Output symbols.json path.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    index = scan_repo(args.repo)
    write_symbols(index, args.out)
    print(f"Wrote {len(index.files)} files to {args.out}")


if __name__ == "__main__":
    main()
