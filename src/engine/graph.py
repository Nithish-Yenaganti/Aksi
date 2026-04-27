"""Phase 2 graph builder: connect imports to definitions and emit box-in-box graph JSON."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(frozen=True)
class GraphNode:
    id: str
    name: str
    kind: str
    path: str
    language: str | None = None
    sha256: str | None = None
    line: int | None = None
    stale: bool = False
    children: list["GraphNode"] = field(default_factory=list)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    source_path: str
    target_path: str
    import_module: str
    import_name: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ArchitectureGraph:
    root: str
    generated_at: str
    tree: GraphNode
    edges: list[GraphEdge]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_graph_from_symbols(symbols: dict[str, Any]) -> ArchitectureGraph:
    files = list(symbols.get("files", []))
    file_nodes = {file["path"]: _file_node(file) for file in files}
    return ArchitectureGraph(
        root=str(symbols["root"]),
        generated_at=datetime.now(timezone.utc).isoformat(),
        tree=_build_tree(str(symbols["root"]), file_nodes),
        edges=_build_edges(files, file_nodes),
    )


def build_graph(symbols_path: Path, output_path: Path | None = None) -> ArchitectureGraph:
    symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
    graph = build_graph_from_symbols(symbols)
    if output_path is not None:
        write_graph(graph, output_path)
    return graph


def write_graph(graph: ArchitectureGraph, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _build_tree(root: str, file_nodes: dict[str, GraphNode]) -> GraphNode:
    project = GraphNode("project:", PurePosixPath(root).name or root, "project", "")
    folders: dict[str, GraphNode] = {"": project}

    for file_path, file_node in sorted(file_nodes.items()):
        parent_path = ""
        for part in PurePosixPath(file_path).parts[:-1]:
            folder_path = part if not parent_path else f"{parent_path}/{part}"
            if folder_path not in folders:
                folder = GraphNode(f"folder:{folder_path}", part, "folder", folder_path)
                folders[parent_path].children.append(folder)
                folders[folder_path] = folder
            parent_path = folder_path
        folders[parent_path].children.append(file_node)

    return _freeze_node(project)


def _file_node(file: dict[str, Any]) -> GraphNode:
    children = []
    for class_record in file.get("classes", []):
        children.append(
            GraphNode(
                id=f"class:{file['path']}:{class_record['name']}",
                name=str(class_record["name"]),
                kind="class",
                path=str(file["path"]),
        line=class_record.get("line"),
                stale=bool(file.get("stale", False)),
            )
        )
    for function_record in file.get("functions", []):
        children.append(
            GraphNode(
                id=f"function:{file['path']}:{function_record['name']}",
                name=str(function_record["name"]),
                kind="function",
                path=str(file["path"]),
        line=function_record.get("line"),
                stale=bool(file.get("stale", False)),
            )
        )
    return GraphNode(
        id=f"file:{file['path']}",
        name=PurePosixPath(str(file["path"])).name,
        kind="file",
        path=str(file["path"]),
        language=str(file["language"]),
        sha256=str(file["sha256"]),
        stale=bool(file.get("stale", False)),
        children=children,
    )


def _build_edges(files: list[dict[str, Any]], file_nodes: dict[str, GraphNode]) -> list[GraphEdge]:
    modules = _module_index(files)
    definitions = _definition_index(files)
    edges: list[GraphEdge] = []

    for source_file in files:
        for import_record in source_file.get("imports", []):
            target_file = _resolve_import_target(source_file, import_record, modules, definitions)
            if target_file is None or target_file["path"] == source_file["path"]:
                continue
            target_id = _resolve_definition_node_id(target_file, import_record.get("name"), file_nodes) or f"file:{target_file['path']}"
            edges.append(
                GraphEdge(
                    source=f"file:{source_file['path']}",
                    target=target_id,
                    kind="imports",
                    source_path=str(source_file["path"]),
                    target_path=str(target_file["path"]),
                    import_module=str(import_record["module"]),
                    import_name=import_record.get("name"),
                    line=import_record.get("line"),
                )
            )
    return edges


def _module_index(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    for file in files:
        path = PurePosixPath(str(file["path"]))
        no_suffix = path.with_suffix("").as_posix()
        modules[no_suffix] = file
        modules[no_suffix.replace("/", ".")] = file
        modules[path.as_posix()] = file
        modules[path.name] = file
    return modules


def _definition_index(files: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for file in files:
        for record in [*file.get("classes", []), *file.get("functions", [])]:
            definitions.setdefault(str(record["name"]), file)
    return definitions


def _resolve_import_target(
    source_file: dict[str, Any],
    import_record: dict[str, Any],
    modules: dict[str, dict[str, Any]],
    definitions: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    module = str(import_record["module"])
    if module in modules:
        return modules[module]
    if module.startswith("./") or module.startswith("../"):
        relative = _resolve_relative_path(str(source_file["path"]), module)
        return modules.get(relative) or modules.get(PurePosixPath(relative).with_suffix("").as_posix())
    if import_record.get("name"):
        return definitions.get(_first_imported_name(str(import_record["name"])))
    return None


def _resolve_definition_node_id(target_file: dict[str, Any], import_name: str | None, file_nodes: dict[str, GraphNode]) -> str | None:
    if not import_name:
        return None
    imported_names = _imported_names(import_name)
    for name in imported_names:
        for child in file_nodes[str(target_file["path"])].children:
            if child.name == name:
                return child.id
    return None


def _resolve_relative_path(source_path: str, module: str) -> str:
    parts: list[str] = []
    for part in PurePosixPath(source_path).parent.joinpath(module).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _first_imported_name(raw: str) -> str:
    names = _imported_names(raw)
    return names[0] if names else raw


def _imported_names(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    names: list[str] = []
    for item in text.split(","):
        name = item.strip()
        if not name:
            continue
        if " as " in name:
            name = name.split(" as ", 1)[0].strip()
        names.append(name)
    return names


def _freeze_node(node: GraphNode) -> GraphNode:
    return GraphNode(
        id=node.id,
        name=node.name,
        kind=node.kind,
        path=node.path,
        language=node.language,
        sha256=node.sha256,
        line=node.line,
        stale=node.stale or any(child.stale for child in node.children),
        children=[_freeze_node(child) for child in node.children],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build graph.json from symbols.json.")
    parser.add_argument("--symbols", type=Path, default=Path("Files/symbols.json"))
    parser.add_argument("--out", type=Path, default=Path("Files/graph.json"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    graph = build_graph(args.symbols, args.out)
    print(f"Wrote {len(graph.edges)} edges to {args.out}")


if __name__ == "__main__":
    main()
