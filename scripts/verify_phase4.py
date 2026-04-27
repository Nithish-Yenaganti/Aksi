from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.engine.graph import build_graph
from src.engine.scanner import scan_repo


def free_port(start: int = 8765) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available local port.")


def wait_for(url: str, process: subprocess.Popen[str]) -> str:
    deadline = time.monotonic() + 6
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                return response.read().decode("utf-8")
        except Exception as error:  # noqa: BLE001 - verifier reports startup failure.
            last_error = error
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise RuntimeError(f"Server exited early.\nstdout:\n{stdout}\nstderr:\n{stderr}") from error
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def main() -> None:
    scan_repo(Path("tests/fixtures/phase1_repo"), Path("Files/symbols.json"))
    build_graph(Path("Files/symbols.json"), Path("Files/graph.json"))

    html = Path("src/web/static/index.html").read_text(encoding="utf-8")
    script = Path("src/web/static/script.js").read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/d3@7" in html
    assert "d3.treemap" in script
    assert "d3.zoom" in script
    assert "fetch(\"/graph.json\")" in script

    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "src.web.app",
            "--stdlib",
            "--files",
            "Files",
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
        page = wait_for(f"http://127.0.0.1:{port}/src/web/static/index.html", process)
        graph = wait_for(f"http://127.0.0.1:{port}/graph.json", process)
        assert "Aksi Cognitive Map" in page
        assert "pkg/service.py" in graph
        assert "web/widget.js" in graph
        print(f"Phase 4 gate passed: http://127.0.0.1:{port}/src/web/static/index.html")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
