from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi.graph import build_project_graph, write_graph
from aksi.scanner import scan_repo, write_symbols
from aksi.visualizer import write_visualization


def free_port(start: int = 8765, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No available localhost port in range {start}-{start + attempts - 1}")


def fetch_text(url: str, timeout: float = 5.0) -> str:
    with urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def wait_for(url: str, process: subprocess.Popen[str], timeout_seconds: float = 5.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return fetch_text(url, timeout=1.0)
        except Exception as error:  # noqa: BLE001 - verifier reports the final connection failure.
            last_error = error
            if process.poll() is not None:
                _, stderr = process.communicate(timeout=1)
                raise RuntimeError(f"Server exited before responding: {stderr.strip()}") from error
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> None:
    repo = Path("tests/fixtures/polyglot")
    output_dir = Path("Files")

    index = scan_repo(repo)
    graph = build_project_graph(index)
    write_symbols(index, output_dir / "symbols.json")
    write_graph(graph, output_dir / "index.json")
    html_path = write_visualization(output_dir)

    html = html_path.read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/d3@7" in html
    assert "d3.treemap" in html
    assert 'fetch("../index.json")' in html

    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "aksi.visualizer",
            "--dir",
            str(output_dir),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        page_url = f"http://127.0.0.1:{port}/graph/index.html"
        graph_url = f"http://127.0.0.1:{port}/index.json"
        served_html = wait_for(page_url, process)
        served_graph = fetch_text(graph_url)

        assert "Aksi Map" in served_html
        assert "d3.zoom" in served_html
        assert "src/greeter.py" in served_graph
        assert "web/message.js" in served_graph
        print(f"Phase 4 verified: {page_url}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
