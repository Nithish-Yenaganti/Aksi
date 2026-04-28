"""Aksi source scanner.

The scanner turns source files into a flat, language-aware inventory. It uses
Tree-sitter when a grammar is available and small text fallbacks only for import
normalization and resilience.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shelve
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    from tree_sitter import Language, Parser
except Exception:  # pragma: no cover - dependency error is reported at runtime
    Language = None  # type: ignore[assignment]
    Parser = None  # type: ignore[assignment]


SCANNER_VERSION = "0.1.0"
FILES_DIR_NAME = "Files"
CACHE_BASENAME = ".aksi_cache"

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    FILES_DIR_NAME,
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "dist",
    "build",
    "target",
    "coverage",
}

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
}

SYMBOL_NODE_TYPES = {
    "function_definition": "function",
    "function_declaration": "function",
    "method_definition": "function",
    "arrow_function": "function",
    "function": "function",
    "class_definition": "class",
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_specifier": "struct",
    "type_declaration": "type",
}

IMPORT_NODE_TYPES = {
    "import_statement",
    "import_from_statement",
    "import_declaration",
    "include_directive",
    "use_declaration",
    "mod_item",
    "package_clause",
}

PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?P<from>[\.\w]+)\s+import\s+(?P<from_names>[\w\*,\s]+)|import\s+(?P<import>[\w\.,\s]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(
    r"(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\()\s*[\"'](?P<module>[^\"']+)[\"']",
    re.MULTILINE,
)
C_INCLUDE_RE = re.compile(r"^\s*#\s*include\s+[<\"](?P<module>[^>\"]+)[>\"]", re.MULTILINE)


@dataclass
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int


@dataclass
class ImportRef:
    import_text: str
    module: str
    start_line: int
    end_line: int


@dataclass
class ScannedFile:
    path: str
    language: str
    hash: str
    stale: bool = False
    changed: bool = False
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)


@dataclass
class ScanResult:
    repo_path: str
    files: list[ScannedFile]
    scanner: dict[str, Any]


def normalized_relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_source_files(root: Path) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS]
        current = Path(current_root)
        for filename in filenames:
            path = current / filename
            if path.suffix.lower() in LANGUAGE_BY_SUFFIX:
                yield path


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, Any] = {}

    def get(self, language_name: str) -> Any | None:
        if Parser is None:
            return None
        if language_name in self._parsers:
            return self._parsers[language_name]
        parser = self._build_parser(language_name)
        self._parsers[language_name] = parser
        return parser

    def _build_parser(self, language_name: str) -> Any | None:
        language = self._load_language(language_name)
        if language is None:
            return None
        parser = Parser()
        try:
            parser.language = language
        except AttributeError:  # pragma: no cover - older tree-sitter API
            parser.set_language(language)
        return parser

    def _load_language(self, language_name: str) -> Any | None:
        candidates = [language_name]
        if language_name == "tsx":
            candidates.extend(["typescript", "javascript"])

        for candidate in candidates:
            try:
                from tree_sitter_languages import get_language

                return get_language(candidate)
            except Exception:
                pass

        if language_name == "python":
            try:
                import tree_sitter_python

                return Language(tree_sitter_python.language())
            except Exception:
                return None
        return None


def node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def name_from_node(source: bytes, node: Any, parent: Any | None = None) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return node_text(source, name_node).strip()

    if node.type == "arrow_function" and parent is not None:
        parent_name = parent.child_by_field_name("name")
        if parent_name is not None:
            return node_text(source, parent_name).strip()

    for child in node.children:
        if child.type in {"identifier", "property_identifier", "type_identifier"}:
            return node_text(source, child).strip()
    return None


def walk_nodes(node: Any, parent: Any | None = None) -> Iterable[tuple[Any, Any | None]]:
    yield node, parent
    for child in node.children:
        yield from walk_nodes(child, node)


def extract_symbols_with_tree_sitter(source: bytes, parser: Any) -> list[Symbol]:
    tree = parser.parse(source)
    symbols: list[Symbol] = []
    seen: set[tuple[str, int, int]] = set()

    for node, parent in walk_nodes(tree.root_node):
        kind = SYMBOL_NODE_TYPES.get(node.type)
        if not kind:
            continue
        name = name_from_node(source, node, parent)
        if not name:
            continue
        key = (name, node.start_point[0], node.end_point[0])
        if key in seen:
            continue
        seen.add(key)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            )
        )
    return sorted(symbols, key=lambda item: (item.start_line, item.name))


def import_module_from_text(language: str, import_text: str) -> str:
    stripped = import_text.strip()
    if language == "python":
        match = PY_IMPORT_RE.search(stripped)
        if match:
            if match.group("from"):
                return match.group("from")
            return match.group("import").split(",")[0].strip()
    if language in {"javascript", "typescript", "tsx"}:
        match = JS_IMPORT_RE.search(stripped)
        if match:
            return match.group("module")
    if language in {"c", "cpp"}:
        match = C_INCLUDE_RE.search(stripped)
        if match:
            return match.group("module")
    return stripped


def extract_imports_with_tree_sitter(source: bytes, language: str, parser: Any) -> list[ImportRef]:
    tree = parser.parse(source)
    imports: list[ImportRef] = []
    seen: set[tuple[str, int]] = set()
    for node, _parent in walk_nodes(tree.root_node):
        if node.type not in IMPORT_NODE_TYPES:
            continue
        text = node_text(source, node).strip()
        module = import_module_from_text(language, text)
        key = (text, node.start_point[0])
        if not module or key in seen:
            continue
        seen.add(key)
        imports.append(
            ImportRef(
                import_text=text,
                module=module,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            )
        )
    return imports


def fallback_extract_symbols(text: str, language: str) -> list[Symbol]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    if language == "python":
        patterns = [
            (re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE), "function"),
            (re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b", re.MULTILINE), "class"),
        ]
    elif language in {"javascript", "typescript", "tsx"}:
        patterns = [
            (re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE), "function"),
            (re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)\b", re.MULTILINE), "class"),
            (re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", re.MULTILINE), "function"),
        ]
    symbols: list[Symbol] = []
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(Symbol(match.group(1), kind, line, line))
    return sorted(symbols, key=lambda item: (item.start_line, item.name))


def fallback_extract_imports(text: str, language: str) -> list[ImportRef]:
    if language == "python":
        pattern = PY_IMPORT_RE
    elif language in {"javascript", "typescript", "tsx"}:
        pattern = JS_IMPORT_RE
    elif language in {"c", "cpp"}:
        pattern = C_INCLUDE_RE
    else:
        return []

    imports: list[ImportRef] = []
    for match in pattern.finditer(text):
        module = match.groupdict().get("module") or match.groupdict().get("from") or match.groupdict().get("import")
        if not module:
            continue
        line = text.count("\n", 0, match.start()) + 1
        import_text = match.group(0).strip()
        imports.append(ImportRef(import_text=import_text, module=module.split(",")[0].strip(), start_line=line, end_line=line))
    return imports


def scan_file(path: Path, root: Path, cache: Any, parsers: ParserRegistry) -> ScannedFile:
    relpath = normalized_relpath(path, root)
    language = LANGUAGE_BY_SUFFIX[path.suffix.lower()]
    file_hash = hash_file(path)
    previous_hash = cache.get(relpath)
    changed = previous_hash is not None and previous_hash != file_hash
    source = path.read_bytes()
    text = source.decode("utf-8", errors="replace")
    parser = parsers.get(language)

    if parser is not None:
        try:
            symbols = extract_symbols_with_tree_sitter(source, parser)
            imports = extract_imports_with_tree_sitter(source, language, parser)
        except Exception:
            symbols = fallback_extract_symbols(text, language)
            imports = fallback_extract_imports(text, language)
    else:
        symbols = fallback_extract_symbols(text, language)
        imports = fallback_extract_imports(text, language)

    return ScannedFile(
        path=relpath,
        language=language,
        hash=file_hash,
        stale=False,
        changed=changed,
        symbols=symbols,
        imports=imports,
    )


def scan_repo(repo_path: str | Path = ".") -> ScanResult:
    root = Path(repo_path).expanduser().resolve()
    files_dir = root / FILES_DIR_NAME
    files_dir.mkdir(exist_ok=True)
    parsers = ParserRegistry()
    scanned: list[ScannedFile] = []

    with shelve.open(str(files_dir / CACHE_BASENAME)) as cache:
        for source_file in iter_source_files(root):
            item = scan_file(source_file, root, cache, parsers)
            scanned.append(item)
            cache[item.path] = item.hash

    return ScanResult(
        repo_path=str(root),
        files=sorted(scanned, key=lambda item: item.path),
        scanner={
            "version": SCANNER_VERSION,
            "files_scanned": len(scanned),
            "languages": sorted({item.language for item in scanned}),
        },
    )


def scan_repo_dict(repo_path: str | Path = ".") -> dict[str, Any]:
    result = scan_repo(repo_path)
    return {
        "repo_path": result.repo_path,
        "scanner": result.scanner,
        "files": [asdict(item) for item in result.files],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a repository with Aksi.")
    parser.add_argument("path", nargs="?", default=".", help="Repository path to scan.")
    args = parser.parse_args()
    print(json.dumps(scan_repo_dict(args.path), indent=2))


if __name__ == "__main__":
    main()
