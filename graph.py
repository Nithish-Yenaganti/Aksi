"""Build Aksi architecture graphs from scanner output."""

from __future__ import annotations

import argparse
import hashlib
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
UNUSED_HINT_CONFIDENCE = "low"
UNUSED_HINT_REASON = (
    "No local static references found; dynamic imports, CLI entrypoints, tests, or framework wiring may still use this node."
)


def slug(value: str) -> str:
    return quote(value.strip(), safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-") or "root"


def folder_id(path: str) -> str:
    return f"folder:{slug(path or '.')}"


def file_id(path: str) -> str:
    return f"file:{slug(path)}"


def symbol_id(path: str, name: str, start_line: int) -> str:
    return f"symbol:{slug(path)}:{slug(name)}:{start_line}"


def compact_ref(value: str, max_prefix: int = 48) -> str:
    normalized = value.strip() or "unknown"
    encoded = slug(normalized)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    if len(encoded) <= max_prefix:
        return f"{encoded}:{digest}"
    return f"{encoded[:max_prefix]}:{digest}"


def external_id(module: str) -> str:
    return f"external:{compact_ref(module)}"


def import_edge_id(path: str, index: int, module: str) -> str:
    return f"edge:{slug(path)}:{index}:{compact_ref(module)}"


def component_id(name: str) -> str:
    return f"component:{slug(name.lower().replace(' ', '-'))}"


def make_node(node_id: str, node_type: str, name: str, path: str, **extra: Any) -> dict[str, Any]:
    node = {"id": node_id, "type": node_type, "name": name, "path": path, "children": []}
    node.update({key: value for key, value in extra.items() if value is not None})
    return node


def set_unused_hint(node: dict[str, Any], unused: bool) -> None:
    node["unused"] = unused
    node["unused_hint"] = unused
    if unused:
        node["unused_confidence"] = UNUSED_HINT_CONFIDENCE
        node["unused_reason"] = UNUSED_HINT_REASON


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
            set_unused_hint(node, True)
            node["dead_reason"] = "No local files import this file; it may be unused or externally invoked."
            unused_files += 1
        else:
            set_unused_hint(node, False)

    for node in nodes.values():
        if node.get("type") not in SYMBOL_TYPES:
            continue
        reference_count = count_symbol_references(node, source_texts)
        node["usage_count"] = reference_count
        if reference_count == 0 and not str(node.get("name", "")).startswith("__"):
            set_unused_hint(node, True)
            node["dead_reason"] = "No local references to this symbol were found outside its declaration line."
            unused_symbols += 1
        else:
            set_unused_hint(node, False)

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


COMPONENT_DEFINITIONS: dict[str, dict[str, str]] = {
    "interface": {
        "name": "Agent and MCP Interface",
        "detail": "Entry points that expose the project to coding agents, clients, or local commands.",
        "why": "This layer is where outside requests enter the project before being routed into internal code.",
        "how": "Aksi groups files with MCP, server, API, route, app, or entrypoint naming into this component.",
        "role": "Receives user or host calls and coordinates the next local operation.",
    },
    "prompt": {
        "name": "Prompt Pipeline",
        "detail": "Code that prepares, transforms, or serves prompt-oriented workflows.",
        "why": "Prompt pipelines are the core behavior in agent-facing projects because they decide how user input becomes structured work.",
        "how": "Aksi groups files whose path or symbols mention prompt processing into this component.",
        "role": "Turns incoming intent into host-ready data or actions.",
    },
    "memory": {
        "name": "Context and Memory",
        "detail": "Persistence, embeddings, retrieval, feedback, and saved context utilities.",
        "why": "This layer lets the project remember useful explanations and retrieve prior knowledge instead of recomputing everything.",
        "how": "Aksi groups files with memory, database, embedding, few-shot, feedback, context, or summary naming into this component.",
        "role": "Stores and retrieves durable context for future runs.",
    },
    "scanner": {
        "name": "Source Scanner",
        "detail": "Static analysis code that reads local files and extracts hashes, symbols, and imports.",
        "why": "The scanner keeps structural discovery local and deterministic, so the LLM host does not guess repo shape.",
        "how": "Aksi groups parser, scanner, tree-sitter, and extraction modules into this component.",
        "role": "Converts source files into a flat inventory of facts.",
    },
    "graph": {
        "name": "Architecture Graph Builder",
        "detail": "Code that converts scanned facts into maps, dependency edges, stale flags, and usage hints.",
        "why": "This layer turns raw scan data into the visual and machine-readable blueprint.",
        "how": "Aksi groups graph, architecture, dependency, and visualization-builder modules into this component.",
        "role": "Builds the repository model consumed by MCP tools and the viewer.",
    },
    "viewer": {
        "name": "Static Viewer",
        "detail": "Browser UI code for rendering structure, runtime flow, architecture, details, and saved summaries.",
        "why": "The viewer makes the local analysis inspectable by humans without requiring a hosted backend.",
        "how": "Aksi groups UI, HTML, rendering, and view modules into this component.",
        "role": "Displays generated maps and summary panels from static JSON data.",
    },
    "scripts": {
        "name": "CLI and Scripts",
        "detail": "Command-line helpers, setup scripts, and standalone local runners.",
        "why": "These files make the project installable, testable, and runnable outside an MCP client.",
        "how": "Aksi groups scripts, setup files, CLIs, and local runner files into this component.",
        "role": "Provides manual and automation entry points for developers.",
    },
    "tests": {
        "name": "Validation Suite",
        "detail": "Tests and fixtures that verify scanner, graph, MCP, and viewer behavior.",
        "why": "This layer protects the expected behavior as the project changes.",
        "how": "Aksi groups files under test directories or with test naming into this component.",
        "role": "Validates local analysis and integration behavior.",
    },
    "core": {
        "name": "Application Core",
        "detail": "General-purpose source files that do not match a more specific architecture component.",
        "why": "Some projects keep essential domain logic in neutral modules that still need architectural representation.",
        "how": "Aksi places unmatched scanned files here after checking more specific component heuristics.",
        "role": "Holds shared or domain-specific implementation code.",
    },
}


def component_role_for_file(path: str, symbols: list[Any]) -> str:
    lowered = path.lower()
    name = Path(path).name.lower()
    symbol_text = " ".join(getattr(symbol, "name", "") for symbol in symbols).lower()
    combined = f"{lowered} {symbol_text}"

    if lowered.startswith(("tests/", "test/")) or name.startswith("test_") or name.endswith(".test.ts"):
        return "tests"
    if lowered.startswith("scripts/") or name in {"aksi.py", "cli.py", "main.py"} or "setup" in combined:
        return "scripts"
    if "mcp" in lowered or name in {"server.py", "server.ts", "server.tsx", "app.py", "app.ts", "app.tsx", "api.py", "api.ts"}:
        return "interface"
    if any(token in combined for token in ("scanner", "parser", "tree_sitter", "tree-sitter", "extract")):
        return "scanner"
    if any(token in combined for token in ("graph", "architecture", "dependency", "visualization")):
        return "graph"
    if lowered.startswith("ui/") or name.endswith(".html") or "viewer" in combined or "render" in combined:
        return "viewer"
    if "prompt" in lowered:
        return "prompt"
    if any(token in combined for token in ("memory", "db", "database", "embedding", "fewshot", "few_shot", "feedback", "context", "summary")):
        return "memory"
    if "prompt" in combined:
        return "prompt"
    if any(token in combined for token in ("mcp", "server", "route", "api", "app.")):
        return "interface"
    return "core"


def add_architecture_components(architecture: dict[str, Any], result: ScanResult) -> None:
    nodes = architecture["nodes"]
    role_files: dict[str, list[str]] = {}
    file_to_component: dict[str, str] = {}
    scanned_by_path = {item.path: item for item in result.files}

    for scanned_file in result.files:
        role = component_role_for_file(scanned_file.path, scanned_file.symbols)
        role_files.setdefault(role, []).append(scanned_file.path)

    components: list[dict[str, Any]] = []
    for role, paths in sorted(role_files.items(), key=lambda item: COMPONENT_DEFINITIONS[item[0]]["name"]):
        definition = COMPONENT_DEFINITIONS[role]
        children = [file_id(path) for path in sorted(paths)]
        stale = any(nodes[child].get("stale") for child in children if child in nodes)
        unused = all(nodes[child].get("unused") for child in children if child in nodes)
        component = make_node(
            component_id(definition["name"]),
            "component",
            definition["name"],
            ".",
            role=role,
            detail=definition["detail"],
            why=definition["why"],
            how=definition["how"],
            stale=stale,
            unused=unused,
            files=sorted(paths),
            file_count=len(paths),
            symbol_count=sum(len(scanned_by_path[path].symbols) for path in paths),
            import_count=sum(len(scanned_by_path[path].imports) for path in paths),
        )
        set_unused_hint(component, unused)
        component["children"] = children
        nodes[component["id"]] = component
        components.append(component)
        for path in paths:
            file_to_component[path] = component["id"]

    component_edge_map: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in architecture.get("edges", []):
        source_node = nodes.get(edge.get("source", ""))
        target_node = nodes.get(edge.get("target", ""))
        if not source_node or not target_node:
            continue
        if source_node.get("type") != "file" or target_node.get("type") != "file":
            continue
        source_component = file_to_component.get(source_node.get("path", ""))
        target_component = file_to_component.get(target_node.get("path", ""))
        if not source_component or not target_component or source_component == target_component:
            continue
        key = (source_component, target_component)
        if key not in component_edge_map:
            component_edge_map[key] = {
                "id": f"component-edge:{slug(source_component)}:{slug(target_component)}",
                "type": "component_dependency",
                "source": source_component,
                "target": target_component,
                "count": 0,
                "imports": [],
            }
        component_edge_map[key]["count"] += 1
        component_edge_map[key]["imports"].append(edge.get("import_text") or edge.get("module") or "")

    for edge in component_edge_map.values():
        imports = [item for item in edge.pop("imports") if item]
        edge["import_text"] = f"{edge['count']} local dependency" + ("" if edge["count"] == 1 else " relationships")
        if imports:
            edge["examples"] = imports[:5]

    architecture["components"] = components
    architecture["component_edges"] = sorted(component_edge_map.values(), key=lambda edge: edge["id"])


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
                    "id": import_edge_id(scanned_file.path, index, import_ref.module),
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
    add_architecture_components(architecture, result)
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

    for component in architecture.get("components", []):
        stale = any(nodes.get(child, {}).get("stale") for child in component.get("children", []))
        component["stale"] = stale
        if component.get("id") in nodes:
            nodes[component["id"]]["stale"] = stale

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
        "components": len(architecture.get("components", [])),
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
