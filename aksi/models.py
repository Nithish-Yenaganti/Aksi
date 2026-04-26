from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SymbolKind = Literal["class", "function", "method", "constant", "export"]


@dataclass(frozen=True)
class ImportRecord:
    module: str
    name: str | None = None
    raw: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ExportRecord:
    name: str
    kind: str
    line: int | None = None


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: SymbolKind
    signature: str | None
    docstring: str | None
    start_line: int
    end_line: int | None = None


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    sha256: str
    stale: bool = False
    imports: list[ImportRecord] = field(default_factory=list)
    exports: list[ExportRecord] = field(default_factory=list)
    symbols: list[SymbolRecord] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolIndex:
    root: str
    generated_at: str
    files: list[FileRecord]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GraphNode:
    id: str
    name: str
    kind: Literal["project", "folder", "file", "symbol"]
    path: str
    language: str | None = None
    sha256: str | None = None
    stale: bool = False
    symbol_kind: SymbolKind | None = None
    signature: str | None = None
    docstring: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    children: list["GraphNode"] = field(default_factory=list)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: Literal["imports"]
    source_path: str
    target_path: str
    import_module: str
    import_name: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class ProjectGraph:
    root: str
    generated_at: str
    tree: GraphNode
    edges: list[GraphEdge]

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)
