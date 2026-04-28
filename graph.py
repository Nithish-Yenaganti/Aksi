"""Build Aksi architecture graphs from scanner output."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scanner import FILES_DIR_NAME, ScanResult, ScannedFile, hash_file, scan_repo

ARCHITECTURE_FILENAME = "architecture.json"


def slug(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.:/-]+", "-", value.strip())
    return safe.strip("-") or "root"


def folder_id(path: str) -> str:
    return f"folder:{slug(path or '.')}"


def file_id(path: str) -> str:
    return f"file:{slug(path)}"


def symbol_id(path: str, name: str, start_line: int) -> str:
    return f"symbol:{slug(path)}:{slug(name)}:{start_line}"


def external_id(module: str) -> str:
    return f"external:{slug(module)}"


def make_node(node_id: str, node_type: str, name: str, path: str, **extra: Any) -> dict[str, Any]:
    node = {"id": node_id, "type": node_type, "name": name, "path": path, "children": []}
    node.update({key: value for key, value in extra.items() if value is not None})
    return node


def ensure_folder(nodes: dict[str, dict[str, Any]], parent_id: str, folder_path: str) -> str:
    current_path = ""
    current_parent = parent_id
    for part in Path(folder_path).parts:
        current_path = f"{current_path}/{part}" if current_path else part
        current_id = folder_id(current_path)
        if current_id not in nodes:
            nodes[current_id] = make_node(current_id, "folder", part, current_path)
            nodes[current_parent]["children"].append(current_id)
        current_parent = current_id
    return current_parent


def candidate_paths_for_import(module: str, importer_path: str, all_paths: set[str]) -> list[str]:
    candidates: list[str] = []
    importer_dir = Path(importer_path).parent
    normalized = module.strip()

    if normalized.startswith("."):
        base = importer_dir
        while normalized.startswith("."):
            normalized = normalized[1:]
            if base != Path("."):
                base = base.parent
        if normalized:
            candidates.append((base / normalized.replace(".", "/")).as_posix())
    elif normalized.startswith(("./", "../")):
        candidates.append((importer_dir / normalized).as_posix())
    else:
        candidates.append(normalized.replace(".", "/"))
        candidates.append(normalized)

    suffixes = ["", ".py", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.ts", "/__init__.py"]
    expanded: list[str] = []
    for candidate in candidates:
        candidate = str(Path(candidate)).replace("\\", "/")
        for suffix in suffixes:
            expanded.append(f"{candidate}{suffix}")

    return [item for item in expanded if item in all_paths]


def resolve_import_target(module: str, importer_path: str, all_paths: set[str]) -> str | None:
    candidates = candidate_paths_for_import(module, importer_path, all_paths)
    if candidates:
        return file_id(candidates[0])
    return None


def build_architecture(result: ScanResult) -> dict[str, Any]:
    root_id = "repo:."
    root_path = Path(result.repo_path)
    nodes: dict[str, dict[str, Any]] = {
        root_id: make_node(root_id, "repo", root_path.name or str(root_path), ".", stale=False)
    }
    edges: list[dict[str, Any]] = []
    all_paths = {item.path for item in result.files}

    for scanned_file in result.files:
        parent_id = root_id
        folder = Path(scanned_file.path).parent.as_posix()
        if folder != ".":
            parent_id = ensure_folder(nodes, root_id, folder)

        current_file_id = file_id(scanned_file.path)
        file_node = make_node(
            current_file_id,
            "file",
            Path(scanned_file.path).name,
            scanned_file.path,
            language=scanned_file.language,
            hash=scanned_file.hash,
            stale=scanned_file.stale,
            changed=scanned_file.changed,
        )
        nodes[current_file_id] = file_node
        nodes[parent_id]["children"].append(current_file_id)

        for symbol in scanned_file.symbols:
            current_symbol_id = symbol_id(scanned_file.path, symbol.name, symbol.start_line)
            nodes[current_symbol_id] = make_node(
                current_symbol_id,
                symbol.kind,
                symbol.name,
                scanned_file.path,
                language=scanned_file.language,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                stale=scanned_file.stale,
            )
            file_node["children"].append(current_symbol_id)

        for index, import_ref in enumerate(scanned_file.imports, start=1):
            target = resolve_import_target(import_ref.module, scanned_file.path, all_paths)
            if target is None:
                target = external_id(import_ref.module)
                if target not in nodes:
                    nodes[target] = make_node(target, "external", import_ref.module, import_ref.module)
            edges.append(
                {
                    "id": f"edge:{slug(scanned_file.path)}:{index}:{slug(import_ref.module)}",
                    "type": "import",
                    "source": current_file_id,
                    "target": target,
                    "import_text": import_ref.import_text,
                    "module": import_ref.module,
                }
            )

    return {
        "root": root_id,
        "nodes": nodes,
        "edges": edges,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanner": result.scanner,
    }


def architecture_path(repo_path: str | Path = ".") -> Path:
    return Path(repo_path).expanduser().resolve() / FILES_DIR_NAME / ARCHITECTURE_FILENAME


def write_architecture(repo_path: str | Path = ".") -> dict[str, Any]:
    result = scan_repo(repo_path)
    architecture = build_architecture(result)
    output_path = architecture_path(repo_path)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(architecture, indent=2), encoding="utf-8")
    return architecture


def load_architecture(repo_path: str | Path = ".") -> dict[str, Any]:
    path = architecture_path(repo_path)
    if not path.exists():
        return write_architecture(repo_path)
    return json.loads(path.read_text(encoding="utf-8"))


def refresh_stale_flags(architecture: dict[str, Any], repo_path: str | Path = ".") -> dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    nodes = architecture.get("nodes", {})
    stale_by_path: dict[str, bool] = {}
    for node in nodes.values():
        if node.get("type") != "file":
            continue
        relpath = node.get("path")
        saved_hash = node.get("hash")
        if not relpath or not saved_hash:
            continue
        current_path = root / relpath
        stale_by_path[relpath] = not current_path.exists() or hash_file(current_path) != saved_hash

    for node in nodes.values():
        relpath = node.get("path")
        if relpath in stale_by_path:
            node["stale"] = stale_by_path[relpath]
    architecture["scanner"] = {**architecture.get("scanner", {}), "stale_files": sum(stale_by_path.values())}
    return architecture


def summarize_architecture(architecture: dict[str, Any]) -> dict[str, Any]:
    nodes = architecture.get("nodes", {})
    files = [node for node in nodes.values() if node.get("type") == "file"]
    symbols = [
        node
        for node in nodes.values()
        if node.get("type") in {"function", "class", "interface", "struct", "type"}
    ]
    return {
        "files": len(files),
        "symbols": len(symbols),
        "edges": len(architecture.get("edges", [])),
        "stale_files": sum(1 for node in files if node.get("stale")),
        "generated_at": architecture.get("generated_at"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Aksi architecture graph.")
    parser.add_argument("path", nargs="?", default=".", help="Repository path to scan.")
    args = parser.parse_args()
    architecture = write_architecture(args.path)
    print(json.dumps(summarize_architecture(architecture), indent=2))


if __name__ == "__main__":
    main()
