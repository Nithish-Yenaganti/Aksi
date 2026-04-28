from pathlib import Path

from scanner import iter_source_files, scan_repo


def test_scanner_extracts_python_symbols_and_imports(tmp_path: Path) -> None:
    (tmp_path / "models.py").write_text("class User:\n    pass\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from models import User\n\n"
        "def run():\n"
        "    return User()\n",
        encoding="utf-8",
    )

    result = scan_repo(tmp_path)
    app = next(item for item in result.files if item.path == "app.py")
    models = next(item for item in result.files if item.path == "models.py")

    assert [symbol.name for symbol in app.symbols] == ["run"]
    assert [symbol.name for symbol in models.symbols] == ["User"]
    assert app.imports[0].module == "models"


def test_scanner_extracts_javascript_symbols_and_imports_with_fallback(tmp_path: Path) -> None:
    (tmp_path / "lib.js").write_text("export function helper() { return 1; }\n", encoding="utf-8")
    (tmp_path / "app.js").write_text(
        "import { helper } from './lib.js';\n"
        "const run = () => helper();\n",
        encoding="utf-8",
    )

    result = scan_repo(tmp_path)
    app = next(item for item in result.files if item.path == "app.js")
    lib = next(item for item in result.files if item.path == "lib.js")

    assert any(symbol.name == "run" for symbol in app.symbols)
    assert any(symbol.name == "helper" for symbol in lib.symbols)
    assert app.imports[0].module == "./lib.js"


def test_scanner_skips_generated_and_dependency_directories(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.py").write_text("def nope(): pass\n", encoding="utf-8")
    (tmp_path / "Files").mkdir()
    (tmp_path / "Files" / "skip.py").write_text("def nope(): pass\n", encoding="utf-8")
    (tmp_path / "keep.py").write_text("def yes(): pass\n", encoding="utf-8")

    paths = [item.relative_to(tmp_path).as_posix() for item in iter_source_files(tmp_path)]

    assert paths == ["keep.py"]


def test_scanner_marks_changed_files_after_previous_scan(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    scan_repo(tmp_path)

    target.write_text("def run():\n    return 2\n", encoding="utf-8")
    result = scan_repo(tmp_path)
    app = next(item for item in result.files if item.path == "app.py")

    assert app.changed is True

