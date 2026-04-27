from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.scanner import scan_repo


def main() -> None:
    output = Path("Files/symbols.json")
    index = scan_repo(Path("tests/fixtures/phase1_repo"), output)
    data = index.to_dict()

    assert output.exists(), "symbols.json was not written"
    assert len(data["files"]) == 3, data
    assert {file["language"] for file in data["files"]} == {"python", "javascript", "typescript"}

    functions = {symbol["name"] for file in data["files"] for symbol in file["functions"]}
    classes = {symbol["name"] for file in data["files"] for symbol in file["classes"]}
    imports = {record["module"] for file in data["files"] for record in file["imports"]}

    assert {"run", "make_service", "renderWidget", "label"}.issubset(functions), functions
    assert {"Service", "Widget"}.issubset(classes), classes
    assert {"os", "web.widget", "./label"}.issubset(imports), imports
    assert all(len(file["sha256"]) == 64 for file in data["files"])

    print(json.dumps(data, indent=2, sort_keys=True))
    print(f"\nPhase 1 gate passed using parser backend: {data['parser_backend']}")


if __name__ == "__main__":
    main()
