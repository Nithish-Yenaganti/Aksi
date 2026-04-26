from __future__ import annotations

import json
from os import PathLike
from pathlib import PurePosixPath

from .models import FileRecord, GraphEdge, GraphNode, ProjectGraph, SymbolIndex


def build_project_graph(index: SymbolIndex) -> ProjectGraph:
    file_nodes = {
        file.path: _file_node(file)
        for file in index.files
    }
    tree = _build_tree(file_nodes, index.root)
    edges = _build_edges(index, file_nodes)
    return ProjectGraph(
        root=index.root,
        generated_at=index.generated_at,
        tree=tree,
        edges=edges,
    )


def write_graph(graph: ProjectGraph, output_path: str | PathLike[str]) -> None:
    from pathlib import Path

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(graph.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_tree(file_nodes: dict[str, GraphNode], root: str) -> GraphNode:
    root_node = _mutable_node(
        id="project:",
        name=PurePosixPath(root).name or root,
        kind="project",
        path="",
    )
    folders: dict[str, GraphNode] = {"": root_node}

    for file_path, file_node in sorted(file_nodes.items()):
        parts = PurePosixPath(file_path).parts
        parent_path = ""
        for part in parts[:-1]:
            folder_path = _join_posix(parent_path, part)
            if folder_path not in folders:
                folder_node = _mutable_node(
                    id=f"folder:{folder_path}",
                    name=part,
                    kind="folder",
                    path=folder_path,
                )
                folders[parent_path].children.append(folder_node)
                folders[folder_path] = folder_node
            parent_path = folder_path
        folders[parent_path].children.append(file_node)

    return _freeze_node(root_node)


def _build_edges(index: SymbolIndex, file_nodes: dict[str, GraphNode]) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    files_by_path = {file.path: file for file in index.files}
    module_to_file = _module_index(index.files)
    export_to_file = _export_index(index.files)

    for source_file in index.files:
        source_node = file_nodes[source_file.path]
        for import_record in source_file.imports:
            target_file = _resolve_import_target(
                source_file=source_file,
                import_module=import_record.module,
                module_to_file=module_to_file,
                files_by_path=files_by_path,
            )
            if target_file is None and import_record.name:
                target_file = export_to_file.get(import_record.name)
            if target_file is None or target_file.path == source_file.path:
                continue

            target_node_id = _resolve_symbol_node_id(
                target_file=target_file,
                imported_name=import_record.name,
                file_nodes=file_nodes,
            )
            edges.append(
                GraphEdge(
                    source=source_node.id,
                    target=target_node_id or file_nodes[target_file.path].id,
                    kind="imports",
                    source_path=source_file.path,
                    target_path=target_file.path,
                    import_module=import_record.module,
                    import_name=import_record.name,
                    line=import_record.line,
                )
            )

    return edges


def _file_node(file: FileRecord) -> GraphNode:
    children = [
        GraphNode(
            id=f"symbol:{file.path}:{symbol.name}",
            name=symbol.name,
            kind="symbol",
            path=file.path,
            symbol_kind=symbol.kind,
            signature=symbol.signature,
            docstring=symbol.docstring,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
        )
        for symbol in file.symbols
    ]
    return GraphNode(
        id=f"file:{file.path}",
        name=PurePosixPath(file.path).name,
        kind="file",
        path=file.path,
        language=file.language,
        sha256=file.sha256,
        stale=file.stale,
        children=children,
    )


def _module_index(files: list[FileRecord]) -> dict[str, FileRecord]:
    modules: dict[str, FileRecord] = {}
    for file in files:
        path = PurePosixPath(file.path)
        no_suffix = path.with_suffix("").as_posix()
        dotted = no_suffix.replace("/", ".")
        modules[dotted] = file
        modules[path.as_posix()] = file
        modules[path.name] = file
        if path.name == "__init__.py":
            modules[PurePosixPath(no_suffix).parent.as_posix().replace("/", ".")] = file
    return modules


def _export_index(files: list[FileRecord]) -> dict[str, FileRecord]:
    exports: dict[str, FileRecord] = {}
    for file in files:
        for export in file.exports:
            exports.setdefault(export.name, file)
    return exports


def _resolve_import_target(
    *,
    source_file: FileRecord,
    import_module: str,
    module_to_file: dict[str, FileRecord],
    files_by_path: dict[str, FileRecord],
) -> FileRecord | None:
    normalized = import_module.strip()
    if normalized in module_to_file:
        return module_to_file[normalized]

    if normalized.startswith("."):
        python_relative = _resolve_python_relative(source_file.path, normalized)
        if python_relative in module_to_file:
            return module_to_file[python_relative]

    if normalized.startswith("..") or normalized.startswith("./"):
        relative_path = _resolve_path_relative(source_file.path, normalized)
        if relative_path in files_by_path:
            return files_by_path[relative_path]
        no_suffix = PurePosixPath(relative_path).with_suffix("").as_posix().replace("/", ".")
        return module_to_file.get(no_suffix)

    return None


def _resolve_symbol_node_id(
    *,
    target_file: FileRecord,
    imported_name: str | None,
    file_nodes: dict[str, GraphNode],
) -> str | None:
    if imported_name is None:
        return None
    names = _imported_names(imported_name)
    target_file_node = file_nodes[target_file.path]
    for name in names:
        for child in target_file_node.children:
            if child.name == name or child.name.endswith(f".{name}"):
                return child.id
    return None


def _imported_names(raw_name: str) -> list[str]:
    text = raw_name.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    names = []
    for item in text.split(","):
        name = item.strip()
        if not name:
            continue
        if " as " in name:
            name = name.split(" as ", 1)[0].strip()
        names.append(name)
    return names


def _resolve_python_relative(source_path: str, module: str) -> str:
    leading_dots = len(module) - len(module.lstrip("."))
    remainder = module.lstrip(".")
    base = PurePosixPath(source_path).parent
    for _ in range(max(leading_dots - 1, 0)):
        base = base.parent
    if remainder:
        return _join_posix(base.as_posix(), remainder.replace(".", "/")).replace("/", ".")
    return base.as_posix().replace("/", ".")


def _resolve_path_relative(source_path: str, module: str) -> str:
    source_parent = PurePosixPath(source_path).parent
    combined = source_parent.joinpath(module)
    parts: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts).as_posix()


def _join_posix(left: str, right: str) -> str:
    return right if not left else f"{left}/{right}"


def _mutable_node(
    *,
    id: str,
    name: str,
    kind: str,
    path: str,
) -> GraphNode:
    return GraphNode(id=id, name=name, kind=kind, path=path)


def _freeze_node(node: GraphNode) -> GraphNode:
    return GraphNode(
        id=node.id,
        name=node.name,
        kind=node.kind,
        path=node.path,
        language=node.language,
        sha256=node.sha256,
        stale=node.stale,
        symbol_kind=node.symbol_kind,
        signature=node.signature,
        docstring=node.docstring,
        start_line=node.start_line,
        end_line=node.end_line,
        children=[_freeze_node(child) for child in node.children],
    )
