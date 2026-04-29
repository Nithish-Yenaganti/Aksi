"""Build Aksi architecture graphs from scanner output."""

from __future__ import annotations

import argparse
import json
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from scanner import FILES_DIR_NAME, ScanResult, hash_file, scan_repo

ARCHITECTURE_FILENAME = "architecture.json"
SYMBOL_TYPES = {"function", "class", "interface", "struct", "type"}
ENTRYPOINT_FILENAMES = {
    "__init__.py",
    "aksi.py",
    "app.py",
    "cli.py",
    "index.js",
    "index.ts",
    "index.tsx",
    "main.py",
    "main.ts",
    "main.tsx",
    "mcp_server.py",
    "server.py",
    "server.ts",
    "server.tsx",
}


def slug(value: str) -> str:
    return quote(value.strip(), safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-") or "root"


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
    importer_dir = Path(importer_path).parent.as_posix()
    if importer_dir == ".":
        importer_dir = ""
    normalized = module.strip()

    if normalized.startswith(("./", "../")):
        candidates.append(posixpath.normpath(posixpath.join(importer_dir, normalized)))
    elif normalized.startswith("."):
        dot_count = len(normalized) - len(normalized.lstrip("."))
        remainder = normalized[dot_count:]
        base = Path(importer_dir or ".")
        for _ in range(max(0, dot_count - 1)):
            if base != Path("."):
                base = base.parent
        if remainder:
            candidates.append((base / remainder.replace(".", "/")).as_posix())
        else:
            candidates.append(base.as_posix())
    else:
        candidates.append(normalized.replace(".", "/"))
        candidates.append(normalized)

    suffixes = [
        "",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        "/index.js",
        "/index.jsx",
        "/index.ts",
        "/index.tsx",
        "/__init__.py",
    ]
    expanded: list[str] = []
    for candidate in candidates:
        candidate = posixpath.normpath(str(candidate).replace("\\", "/"))
        for suffix in suffixes:
            expanded.append(f"{candidate}{suffix}")
        if candidate.endswith(".js"):
            expanded.extend([f"{candidate[:-3]}.ts", f"{candidate[:-3]}.tsx"])
        if candidate.endswith(".jsx"):
            expanded.append(f"{candidate[:-4]}.tsx")

    return [item for item in expanded if item in all_paths]


def resolve_import_target(module: str, importer_path: str, all_paths: set[str]) -> str | None:
    target_path = resolve_import_path(module, importer_path, all_paths)
    if target_path:
        return file_id(target_path)
    return None


def resolve_import_path(module: str, importer_path: str, all_paths: set[str]) -> str | None:
    candidates = candidate_paths_for_import(module, importer_path, all_paths)
    if candidates:
        return candidates[0]
    return None


def is_probable_entrypoint(path: str) -> bool:
    name = Path(path).name
    return name in ENTRYPOINT_FILENAMES or path.startswith("tests/") or path.startswith("test/")


def identifier_pattern(name: str) -> re.Pattern[str] | None:
    if not name or not re.match(r"^[A-Za-z_$][\w$]*$", name):
        return None
    return re.compile(rf"(?<![\w$]){re.escape(name)}(?![\w$])")


def line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def read_source_texts(result: ScanResult) -> dict[str, str]:
    root = Path(result.repo_path)
    texts: dict[str, str] = {}
    for scanned_file in result.files:
        try:
            texts[scanned_file.path] = (root / scanned_file.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            texts[scanned_file.path] = ""
    return texts


def count_symbol_references(symbol_node: dict[str, Any], source_texts: dict[str, str]) -> int:
    pattern = identifier_pattern(symbol_node.get("name", ""))
    if pattern is None:
        return 0

    count = 0
    declaration_path = symbol_node.get("path")
    declaration_line = symbol_node.get("start_line")
    for path, text in source_texts.items():
        for match in pattern.finditer(text):
            if path == declaration_path and line_number_for_offset(text, match.start()) == declaration_line:
                continue
            count += 1
    return count


def annotate_usage(
    architecture: dict[str, Any],
    result: ScanResult,
    local_import_targets: list[str],
    local_import_sources: list[str],
) -> None:
    nodes = architecture["nodes"]
    source_texts = read_source_texts(result)
    incoming_by_file = {item.path: 0 for item in result.files}
    outgoing_by_file = {item.path: 0 for item in result.files}

    for target_path in local_import_targets:
        if target_path in incoming_by_file:
            incoming_by_file[target_path] += 1
    for source_path in local_import_sources:
        if source_path in outgoing_by_file:
            outgoing_by_file[source_path] += 1

    unused_files = 0
    unused_symbols = 0

    for node in nodes.values():
        if node.get("type") != "file":
            continue
        path = node.get("path", "")
        incoming_count = incoming_by_file.get(path, 0)
        outgoing_count = outgoing_by_file.get(path, 0)
        node["usage_count"] = incoming_count
        node["outgoing_usage_count"] = outgoing_count
        if incoming_count == 0 and outgoing_count == 0 and not is_probable_entrypoint(path):
            node["unused"] = True
            node["dead_reason"] = "No local files import this file; it may be unused or externally invoked."
            unused_files += 1
        else:
            node["unused"] = False

    for node in nodes.values():
        if node.get("type") not in SYMBOL_TYPES:
            continue
        reference_count = count_symbol_references(node, source_texts)
        node["usage_count"] = reference_count
        if reference_count == 0 and not str(node.get("name", "")).startswith("__"):
            node["unused"] = True
            node["dead_reason"] = "No local references to this symbol were found outside its declaration line."
            unused_symbols += 1
        else:
            node["unused"] = False

    architecture["analysis"] = {
        "unused_files": unused_files,
        "unused_symbols": unused_symbols,
        "note": "Unused markers are conservative local static-analysis hints, not runtime proof.",
    }


def repo_summary(result: ScanResult) -> str:
    languages: dict[str, int] = {}
    for item in result.files:
        languages[item.language] = languages.get(item.language, 0) + 1
    language_text = ", ".join(f"{count} {language}" for language, count in sorted(languages.items()))
    symbol_count = sum(len(item.symbols) for item in result.files)
    import_count = sum(len(item.imports) for item in result.files)
    return (
        f"This repository contains {len(result.files)} scanned source files"
        f" ({language_text or 'no detected languages'}), {symbol_count} symbols, and {import_count} import references."
    )


def build_architecture(result: ScanResult) -> dict[str, Any]:
    root_id = "repo:."
    root_path = Path(result.repo_path)
    nodes: dict[str, dict[str, Any]] = {
        root_id: make_node(root_id, "repo", root_path.name or str(root_path), ".", stale=False)
    }
    edges: list[dict[str, Any]] = []
    all_paths = {item.path for item in result.files}
    local_import_targets: list[str] = []
    local_import_sources: list[str] = []

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
            target_path = resolve_import_path(import_ref.module, scanned_file.path, all_paths)
            if target_path is None:
                target = external_id(import_ref.module)
                if target not in nodes:
                    nodes[target] = make_node(target, "external", import_ref.module, import_ref.module)
            else:
                target = file_id(target_path)
                local_import_targets.append(target_path)
                local_import_sources.append(scanned_file.path)
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

    architecture = {
        "root": root_id,
        "nodes": nodes,
        "edges": edges,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanner": result.scanner,
        "repo_summary": repo_summary(result),
    }
    annotate_usage(architecture, result, local_import_targets, local_import_sources)
    return architecture


def architecture_path(repo_path: str | Path = ".") -> Path:
    return Path(repo_path).expanduser().resolve() / FILES_DIR_NAME / ARCHITECTURE_FILENAME


def write_architecture(repo_path: str | Path = ".") -> dict[str, Any]:
    result = scan_repo(repo_path)
    architecture = build_architecture(result)
    output_path = architecture_path(repo_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(architecture, indent=2), encoding="utf-8")
    return architecture


def load_architecture(repo_path: str | Path = ".") -> dict[str, Any]:
    path = architecture_path(repo_path)
    if not path.exists():
        return write_architecture(repo_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return write_architecture(repo_path)


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
        try:
            stale_by_path[relpath] = not current_path.exists() or hash_file(current_path) != saved_hash
        except OSError:
            stale_by_path[relpath] = True

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
        "unused_files": architecture.get("analysis", {}).get("unused_files", 0),
        "unused_symbols": architecture.get("analysis", {}).get("unused_symbols", 0),
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
