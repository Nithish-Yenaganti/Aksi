from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi.scanner import scan_repo, write_symbols


def main() -> None:
    repo = Path("tests/fixtures/polyglot")
    output = Path("Files/symbols.json")
    index = scan_repo(repo)
    write_symbols(index, output)

    languages = {file.language for file in index.files}
    symbols = {
        symbol.name
        for file in index.files
        for symbol in file.symbols
    }

    assert {"python", "javascript"}.issubset(languages), languages
    assert {"Greeter", "Greeter.greet", "greet_default", "buildMessage", "MessageView"}.issubset(symbols), symbols
    assert all(file.sha256 and len(file.sha256) == 64 for file in index.files)

    print(json.dumps(index.to_json_dict(), indent=2, sort_keys=True))
    print(f"\nPhase 1 verified: wrote {output} with {len(index.files)} scanned files.")


if __name__ == "__main__":
    main()
