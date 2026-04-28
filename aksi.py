"""One-command runner for Aksi."""

from __future__ import annotations

import argparse
import http.server
import json
import socket
import socketserver
import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Any

from graph import summarize_architecture, write_architecture


def find_free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def run_tests() -> int:
    return subprocess.call([sys.executable, "-m", "pytest"])


def scan(repo: Path) -> dict[str, Any]:
    architecture = write_architecture(repo)
    return summarize_architecture(architecture)


def serve(repo: Path, port: int) -> None:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(repo))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as server:
        print(f"Aksi UI: http://127.0.0.1:{port}/ui/")
        print("Press Ctrl+C to stop.")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a repo and launch the Aksi UI.")
    parser.add_argument("path", nargs="?", default=".", help="Repository path to scan and serve.")
    parser.add_argument("--port", type=int, default=8000, help="Preferred local HTTP port.")
    parser.add_argument("--scan-only", action="store_true", help="Generate Files/architecture.json without serving the UI.")
    parser.add_argument("--test", action="store_true", help="Run the test suite and exit.")
    args = parser.parse_args()

    if args.test:
        raise SystemExit(run_tests())

    repo = Path(args.path).expanduser().resolve()
    summary = scan(repo)
    print(json.dumps(summary, indent=2))

    if args.scan_only:
        return

    port = find_free_port(args.port)
    serve(repo, port)


if __name__ == "__main__":
    main()
