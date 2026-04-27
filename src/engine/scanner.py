"""Phase 1 scanner: walk a repo, hash files, and extract raw code symbols."""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from src.engine.io import write_json_atomic

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "Files",
}


@dataclass(frozen=True)
class SymbolRecord:
    name: str
    kind: str
    line: int | None = None


@dataclass(frozen=True)
class ImportRecord:
    module: str
    name: str | None = None
    raw: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    sha256: str
    functions: list[SymbolRecord] = field(default_factory=list)
    classes: list[SymbolRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)


@dataclass(frozen=True)
class SymbolIndex:
    root: str
    generated_at: str
    parser_backend: str
    files: list[FileRecord]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LanguageParser(Protocol):
    backend_name: str

    def parse_file(self, source: str, language: str) -> tuple[list[SymbolRecord], list[SymbolRecord], list[ImportRecord]]:
        ...


class TreeSitterParser:
    backend_name = "tree-sitter"

    def __init__(self) -> None:
        try:
            from tree_sitter_languages import get_parser
        except ImportError as error:
            raise RuntimeError("tree-sitter-languages is not installed") from error

        self._parsers = {
            "python": get_parser("python"),
            "javascript": get_parser("javascript"),
            "typescript": get_parser("typescript"),
        }

    def parse_file(self, source: str, language: str) -> tuple[list[SymbolRecord], list[SymbolRecord], list[ImportRecord]]:
        tree = self._parsers[language].parse(source.encode("utf-8"))
        functions: list[SymbolRecord] = []
        classes: list[SymbolRecord] = []
        imports: list[ImportRecord] = []
        self._walk(tree.root_node, source.encode("utf-8"), language, functions, classes, imports)
        return functions, classes, imports

    def _walk(
        self,
        node: object,
        source_bytes: bytes,
        language: str,
        functions: list[SymbolRecord],
        classes: list[SymbolRecord],
        imports: list[ImportRecord],
    ) -> None:
        node_type = getattr(node, "type")
        line = int(getattr(node, "start_point")[0]) + 1

        if language == "python":
            if node_type == "function_definition":
                functions.append(SymbolRecord(_node_name(node, source_bytes), "function", line))
            elif node_type == "class_definition":
                classes.append(SymbolRecord(_node_name(node, source_bytes), "class", line))
            elif node_type in {"import_statement", "import_from_statement"}:
                imports.append(_python_import_record(_node_text(node, source_bytes), line))
        else:
            if node_type in {"function_declaration", "method_definition"}:
                functions.append(SymbolRecord(_node_name(node, source_bytes), "function", line))
            elif node_type == "class_declaration":
                classes.append(SymbolRecord(_node_name(node, source_bytes), "class", line))
            elif node_type == "import_statement":
                imports.append(_js_import_record(_node_text(node, source_bytes), line))
            elif node_type == "variable_declarator":
                name_node = getattr(node, "child_by_field_name")("name")
                value_node = getattr(node, "child_by_field_name")("value")
                if name_node is not None and value_node is not None and getattr(value_node, "type") in {"arrow_function", "function"}:
                    functions.append(SymbolRecord(_node_text(name_node, source_bytes), "function", line))

        for child in getattr(node, "children"):
            self._walk(child, source_bytes, language, functions, classes, imports)


class StaticFallbackParser:
    backend_name = "static-fallback"

    _js_import_re = re.compile(r"^\s*import\s+(?:(?P<name>.+?)\s+from\s+)?['\"](?P<module>[^'\"]+)['\"]\s*;?", re.MULTILINE)
    _js_function_re = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\(", re.MULTILINE)
    _js_arrow_re = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)(?:\s*:\s*[^=]+)?\s*=>", re.MULTILINE)
    _js_class_re = re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)", re.MULTILINE)

    def parse_file(self, source: str, language: str) -> tuple[list[SymbolRecord], list[SymbolRecord], list[ImportRecord]]:
        if language == "python":
            return self._parse_python(source)
        return self._parse_javascript_like(source)

    def _parse_python(self, source: str) -> tuple[list[SymbolRecord], list[SymbolRecord], list[ImportRecord]]:
        tree = ast.parse(source)
        functions: list[SymbolRecord] = []
        classes: list[SymbolRecord] = []
        imports: list[ImportRecord] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(SymbolRecord(node.name, "function", node.lineno))
            elif isinstance(node, ast.ClassDef):
                classes.append(SymbolRecord(node.name, "class", node.lineno))
            elif isinstance(node, ast.Import):
                imports.extend(ImportRecord(alias.name, alias.asname, line=node.lineno) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                imports.extend(ImportRecord(module, alias.name, line=node.lineno) for alias in node.names)

        return functions, classes, imports

    def _parse_javascript_like(self, source: str) -> tuple[list[SymbolRecord], list[SymbolRecord], list[ImportRecord]]:
        functions = [
            SymbolRecord(match.group("name"), "function", _line_for(source, match.start()))
            for match in [*self._js_function_re.finditer(source), *self._js_arrow_re.finditer(source)]
        ]
        classes = [
            SymbolRecord(match.group("name"), "class", _line_for(source, match.start()))
            for match in self._js_class_re.finditer(source)
        ]
        imports = [
            ImportRecord(match.group("module"), (match.group("name") or "").strip() or None, match.group(0).strip(), _line_for(source, match.start()))
            for match in self._js_import_re.finditer(source)
        ]
        return functions, classes, imports


def scan_repo(root: Path, output_path: Path | None = None, *, require_tree_sitter: bool = False) -> SymbolIndex:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository root is not a directory: {root}")

    parser = _build_parser(require_tree_sitter)
    files: list[FileRecord] = []
    for path in sorted(root.rglob("*")):
        if not _should_scan(path, root):
            continue
        language = SUPPORTED_EXTENSIONS[path.suffix.lower()]
        source = path.read_text(encoding="utf-8")
        functions, classes, imports = parser.parse_file(source, language)
        files.append(
            FileRecord(
                path=path.relative_to(root).as_posix(),
                language=language,
                sha256=file_sha256(path),
                functions=functions,
                classes=classes,
                imports=imports,
            )
        )

    index = SymbolIndex(str(root), datetime.now(timezone.utc).isoformat(), parser.backend_name, files)
    if output_path is not None:
        write_symbols(index, output_path)
    return index


def write_symbols(index: SymbolIndex, output_path: Path) -> None:
    write_json_atomic(output_path, index.to_dict())


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_parser(require_tree_sitter: bool) -> LanguageParser:
    try:
        return TreeSitterParser()
    except RuntimeError:
        if require_tree_sitter:
            raise
        return StaticFallbackParser()


def _should_scan(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    relative_parts = path.relative_to(root).parts
    if any(part in DEFAULT_EXCLUDES for part in relative_parts):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _node_name(node: object, source_bytes: bytes) -> str:
    name_node = getattr(node, "child_by_field_name")("name")
    return _node_text(name_node, source_bytes) if name_node is not None else "<anonymous>"


def _node_text(node: object, source_bytes: bytes) -> str:
    return source_bytes[int(getattr(node, "start_byte")) : int(getattr(node, "end_byte"))].decode("utf-8")


def _python_import_record(raw: str, line: int) -> ImportRecord:
    if raw.startswith("from "):
        match = re.match(r"from\s+(?P<module>\S+)\s+import\s+(?P<name>.+)", raw)
        if match:
            return ImportRecord(match.group("module"), match.group("name").strip(), raw, line)
    if raw.startswith("import "):
        return ImportRecord(raw.replace("import ", "", 1).strip(), raw=raw, line=line)
    return ImportRecord(raw, raw=raw, line=line)


def _js_import_record(raw: str, line: int) -> ImportRecord:
    match = re.match(r"\s*import\s+(?:(?P<name>.+?)\s+from\s+)?['\"](?P<module>[^'\"]+)['\"]", raw)
    if not match:
        return ImportRecord(raw, raw=raw, line=line)
    name = (match.group("name") or "").strip() or None
    return ImportRecord(match.group("module"), name, raw, line)


def _line_for(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a repository into symbols.json.")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--out", type=Path, default=Path("Files/symbols.json"))
    parser.add_argument("--require-tree-sitter", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    index = scan_repo(args.repo, args.out, require_tree_sitter=args.require_tree_sitter)
    print(f"Wrote {len(index.files)} files to {args.out} using {index.parser_backend}")


if __name__ == "__main__":
    main()
