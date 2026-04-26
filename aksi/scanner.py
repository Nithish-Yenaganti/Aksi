from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .hash import file_sha256
from .models import SymbolIndex
from .parsers import file_record_for, parser_for

DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


class ScanError(RuntimeError):
    pass


def scan_repo(root: Path, *, excludes: set[str] | None = None) -> SymbolIndex:
    root = root.resolve()
    if not root.exists():
        raise ScanError(f"Repository root does not exist: {root}")
    if not root.is_dir():
        raise ScanError(f"Repository root is not a directory: {root}")

    ignored = DEFAULT_EXCLUDES | (excludes or set())
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_ignored(path, root, ignored):
            continue
        if parser_for(path) is None:
            continue
        source = path.read_text(encoding="utf-8")
        record = file_record_for(path, root, file_sha256(path), source)
        if record is not None:
            files.append(record)

    return SymbolIndex(
        root=str(root),
        generated_at=datetime.now(timezone.utc).isoformat(),
        files=files,
    )


def write_symbols(index: SymbolIndex, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(index.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_ignored(path: Path, root: Path, ignored: set[str]) -> bool:
    relative_parts = path.relative_to(root).parts
    return any(part in ignored for part in relative_parts)
