"""Phase 4 local web host: serve graph.json and the D3 zoomable viewer."""

from __future__ import annotations

import argparse
import functools
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.engine.context import answer_question, explain_node, search_graph
from src.engine.io import read_json
from src.engine.sync import refresh_stale_state

DEFAULT_FILES_DIR = Path("Files")
DEFAULT_STATIC_DIR = Path("src/web/static")


def create_app(files_dir: Path = DEFAULT_FILES_DIR, static_dir: Path = DEFAULT_STATIC_DIR) -> Any:
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from pydantic import BaseModel
    except ImportError as error:
        raise RuntimeError("FastAPI is not installed. Install project dependencies to run the FastAPI host.") from error

    class ChatRequest(BaseModel):
        question: str

    app = FastAPI(title="Aksi Local Map")
    files_dir = files_dir.resolve()
    static_dir = static_dir.resolve()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/graph.json")
    def graph() -> JSONResponse:
        return JSONResponse(read_json(files_dir / "graph.json"))

    @app.get("/api/search")
    def search(q: str = "") -> JSONResponse:
        return JSONResponse(search_graph(q, files_dir / "symbols.json", files_dir / "graph.json"))

    @app.get("/api/node")
    def node(node_id: str) -> JSONResponse:
        return JSONResponse(explain_node(node_id, files_dir / "symbols.json", files_dir / "graph.json"))

    @app.post("/api/chat")
    def chat(request: ChatRequest) -> JSONResponse:
        return JSONResponse(answer_question(request.question, files_dir / "symbols.json", files_dir / "graph.json"))

    @app.post("/api/refresh")
    def refresh() -> JSONResponse:
        return JSONResponse(refresh_stale_state(files_dir / "symbols.json", files_dir / "graph.json"))

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


def serve_stdlib(
    files_dir: Path = DEFAULT_FILES_DIR,
    host: str = "127.0.0.1",
    port: int = 8765,
    static_dir: Path = DEFAULT_STATIC_DIR,
) -> None:
    """Fallback local host for environments without FastAPI installed."""
    handler = functools.partial(_AksiRequestHandler, directory=str(Path.cwd()))
    _AksiRequestHandler.files_dir = files_dir.resolve()
    _AksiRequestHandler.static_dir = static_dir.resolve()
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Aksi map: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAksi map server stopped.")
    finally:
        server.server_close()


class _AksiRequestHandler(SimpleHTTPRequestHandler):
    files_dir = DEFAULT_FILES_DIR
    static_dir = DEFAULT_STATIC_DIR

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP handler API.
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_file(self.static_dir / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            asset = self.static_dir / unquote(parsed.path.removeprefix("/static/"))
            if asset.is_file() and asset.resolve().is_relative_to(self.static_dir):
                self._send_file(asset, _content_type(asset))
                return
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/graph.json":
            self._send_json(read_json(self.files_dir / "graph.json"))
            return
        if parsed.path == "/api/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            self._send_json(search_graph(query, self.files_dir / "symbols.json", self.files_dir / "graph.json"))
            return
        if parsed.path == "/api/node":
            node_id = parse_qs(parsed.query).get("node_id", [""])[0]
            if not node_id:
                self.send_error(HTTPStatus.BAD_REQUEST, "node_id is required")
                return
            self._send_json(explain_node(node_id, self.files_dir / "symbols.json", self.files_dir / "graph.json"))
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - inherited HTTP handler API.
        parsed = urlparse(self.path)
        if parsed.path == "/api/chat":
            body = self._read_body()
            self._send_json(answer_question(str(body.get("question", "")), self.files_dir / "symbols.json", self.files_dir / "graph.json"))
            return
        if parsed.path == "/api/refresh":
            self._send_json(refresh_stale_state(self.files_dir / "symbols.json", self.files_dir / "graph.json"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, path: Path, content_type: str) -> None:
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _content_type(path: Path) -> str:
    return {
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json",
    }.get(path.suffix.lower(), "application/octet-stream")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Aksi D3 map.")
    parser.add_argument("--files", type=Path, default=DEFAULT_FILES_DIR)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stdlib", action="store_true", help="Use the stdlib fallback server instead of FastAPI.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.stdlib:
        serve_stdlib(args.files, args.host, args.port, args.static)
        return
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("uvicorn is not installed. Use --stdlib for the fallback server.") from error
    uvicorn.run(create_app(args.files, args.static), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
