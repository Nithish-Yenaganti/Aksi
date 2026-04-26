from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ExportRecord, FileRecord, ImportRecord, SymbolRecord


@dataclass(frozen=True)
class ParsedFile:
    imports: list[ImportRecord]
    exports: list[ExportRecord]
    symbols: list[SymbolRecord]


class Parser:
    language: str

    def parse(self, source: str) -> ParsedFile:
        raise NotImplementedError


class PythonParser(Parser):
    language = "python"

    def parse(self, source: str) -> ParsedFile:
        tree = ast.parse(source)
        imports: list[ImportRecord] = []
        exports: list[ExportRecord] = []
        symbols: list[SymbolRecord] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(
                    ImportRecord(module=alias.name, name=alias.asname, line=node.lineno)
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                imports.extend(
                    ImportRecord(module=module, name=alias.name, line=node.lineno)
                    for alias in node.names
                )

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind="class",
                        signature=f"class {node.name}",
                        docstring=ast.get_docstring(node),
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", None),
                    )
                )
                exports.append(ExportRecord(name=node.name, kind="class", line=node.lineno))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(self._function_symbol(child, owner=node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._function_symbol(node))
                exports.append(ExportRecord(name=node.name, kind="function", line=node.lineno))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        symbols.append(
                            SymbolRecord(
                                name=target.id,
                                kind="constant",
                                signature=None,
                                docstring=None,
                                start_line=node.lineno,
                                end_line=getattr(node, "end_lineno", None),
                            )
                        )
                        exports.append(ExportRecord(name=target.id, kind="constant", line=node.lineno))

        return ParsedFile(imports=imports, exports=exports, symbols=symbols)

    def _function_symbol(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str | None = None
    ) -> SymbolRecord:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        name = f"{owner}.{node.name}" if owner else node.name
        return SymbolRecord(
            name=name,
            kind="method" if owner else "function",
            signature=f"{prefix} {node.name}({ast.unparse(node.args)})",
            docstring=ast.get_docstring(node),
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", None),
        )


class JavaScriptParser(Parser):
    language = "javascript"

    _import_from_re = re.compile(
        r"^\s*import\s+(?P<name>.+?)\s+from\s+['\"](?P<module>[^'\"]+)['\"]\s*;?",
        re.MULTILINE,
    )
    _side_effect_import_re = re.compile(
        r"^\s*import\s+['\"](?P<module>[^'\"]+)['\"]\s*;?", re.MULTILINE
    )
    _export_re = re.compile(
        r"^\s*export\s+(?:default\s+)?(?P<kind>async\s+function|function|class|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)",
        re.MULTILINE,
    )
    _function_re = re.compile(
        r"^\s*(?:export\s+)?(?P<async>async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\)",
        re.MULTILINE,
    )
    _arrow_re = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\((?P<args>[^)]*)\)\s*=>",
        re.MULTILINE,
    )
    _class_re = re.compile(
        r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)", re.MULTILINE
    )

    def parse(self, source: str) -> ParsedFile:
        imports = [
            ImportRecord(
                module=match.group("module"),
                name=match.group("name").strip(),
                raw=match.group(0).strip(),
                line=self._line_for(source, match.start()),
            )
            for match in self._import_from_re.finditer(source)
        ]
        imports.extend(
            ImportRecord(
                module=match.group("module"),
                raw=match.group(0).strip(),
                line=self._line_for(source, match.start()),
            )
            for match in self._side_effect_import_re.finditer(source)
        )

        exports = [
            ExportRecord(
                name=match.group("name"),
                kind=match.group("kind").replace("async ", ""),
                line=self._line_for(source, match.start()),
            )
            for match in self._export_re.finditer(source)
        ]

        symbols: list[SymbolRecord] = []
        for match in self._class_re.finditer(source):
            symbols.append(
                SymbolRecord(
                    name=match.group("name"),
                    kind="class",
                    signature=f"class {match.group('name')}",
                    docstring=self._leading_comment(source, match.start()),
                    start_line=self._line_for(source, match.start()),
                )
            )
        for match in self._function_re.finditer(source):
            async_prefix = "async " if match.group("async") else ""
            symbols.append(
                SymbolRecord(
                    name=match.group("name"),
                    kind="function",
                    signature=f"{async_prefix}function {match.group('name')}({match.group('args').strip()})",
                    docstring=self._leading_comment(source, match.start()),
                    start_line=self._line_for(source, match.start()),
                )
            )
        for match in self._arrow_re.finditer(source):
            symbols.append(
                SymbolRecord(
                    name=match.group("name"),
                    kind="function",
                    signature=f"const {match.group('name')} = ({match.group('args').strip()}) =>",
                    docstring=self._leading_comment(source, match.start()),
                    start_line=self._line_for(source, match.start()),
                )
            )

        return ParsedFile(imports=imports, exports=exports, symbols=symbols)

    @staticmethod
    def _line_for(source: str, offset: int) -> int:
        return source.count("\n", 0, offset) + 1

    @staticmethod
    def _leading_comment(source: str, offset: int) -> str | None:
        before = source[:offset].rstrip()
        block = re.search(r"/\*\*(?P<body>.*?)\*/\s*$", before, re.DOTALL)
        if block:
            lines = [re.sub(r"^\s*\*\s?", "", line).strip() for line in block.group("body").splitlines()]
            return "\n".join(line for line in lines if line)
        line = re.search(r"//\s*(?P<body>[^\n]+)\s*$", before)
        return line.group("body").strip() if line else None


class PlainTextParser(Parser):
    language = "text"

    def parse(self, source: str) -> ParsedFile:
        return ParsedFile(imports=[], exports=[], symbols=[])


PARSERS_BY_EXTENSION: dict[str, Parser] = {
    ".py": PythonParser(),
    ".js": JavaScriptParser(),
    ".jsx": JavaScriptParser(),
    ".mjs": JavaScriptParser(),
    ".cjs": JavaScriptParser(),
}


def parser_for(path: Path) -> Parser | None:
    return PARSERS_BY_EXTENSION.get(path.suffix.lower())


def file_record_for(path: Path, root: Path, sha256: str, source: str) -> FileRecord | None:
    parser = parser_for(path)
    if parser is None:
        return None
    parsed = parser.parse(source)
    return FileRecord(
        path=path.relative_to(root).as_posix(),
        language=parser.language,
        sha256=sha256,
        imports=parsed.imports,
        exports=parsed.exports,
        symbols=parsed.symbols,
    )
