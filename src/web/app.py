"""Phase 4 local web host: serve graph.json and the D3 zoomable viewer."""

from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from src.engine.io import read_json

DEFAULT_FILES_DIR = Path("Files")
DEFAULT_STATIC_DIR = Path("src/web/static")


def create_app(files_dir: Path = DEFAULT_FILES_DIR, static_dir: Path = DEFAULT_STATIC_DIR) -> Any:
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise RuntimeError("FastAPI is not installed. Install project dependencies to run the FastAPI host.") from error

    app = FastAPI(title="Aksi Local Map")
    files_dir = files_dir.resolve()
    static_dir = static_dir.resolve()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/graph.json")
    def graph() -> JSONResponse:
        return JSONResponse(read_json(files_dir / "graph.json"))

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


def serve_stdlib(files_dir: Path = DEFAULT_FILES_DIR, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Fallback local host for environments without FastAPI installed."""
    handler = functools.partial(_AksiRequestHandler, directory=str(Path.cwd()))
    _AksiRequestHandler.files_dir = files_dir
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Aksi map: http://{host}:{port}/src/web/static/index.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAksi map server stopped.")
    finally:
        server.server_close()


class _AksiRequestHandler(SimpleHTTPRequestHandler):
    files_dir = DEFAULT_FILES_DIR

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP handler API.
        if self.path == "/graph.json":
            payload = (self.files_dir / "graph.json").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the Aksi D3 map.")
    parser.add_argument("--files", type=Path, default=DEFAULT_FILES_DIR)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stdlib", action="store_true", help="Use the stdlib fallback server instead of FastAPI.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.stdlib:
        serve_stdlib(args.files, args.host, args.port)
        return
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("uvicorn is not installed. Use --stdlib for the fallback server.") from error
    uvicorn.run(create_app(args.files), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
