from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi import build_all


def free_port(start: int = 8780) -> int:
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


def post_json(url: str, payload: dict[str, str]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    result = build_all(Path("tests/fixtures/phase1_repo"), Path("Files"))
    assert result["files"] == 3, result
    assert result["context_artifacts"] >= 6, result
    assert Path("Files/context/web__widget.js.json").exists()
    assert Path("Files/context/functions/web__widget.js--renderWidget.json").exists()

    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "aksi.py",
            "tests/fixtures/phase1_repo",
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
        page = wait_for(f"http://127.0.0.1:{port}/", process)
        graph = wait_for(f"http://127.0.0.1:{port}/graph.json", process)
        search = wait_for(f"http://127.0.0.1:{port}/api/search?q=renderWidget", process)
        answer = post_json(f"http://127.0.0.1:{port}/api/chat", {"question": "renderWidget"})
        assert "Aksi Cognitive Map" in page
        assert "web/widget.js" in graph
        assert "web/widget.js" in search
        assert answer["matches"], answer
        print(f"Product flow gate passed: http://127.0.0.1:{port}/")
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    main()
