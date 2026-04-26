from __future__ import annotations

from typing import Any

from . import mcp_tools


def create_server() -> Any:
    try:
        from fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "FastMCP is not installed. Install the MCP extra with: "
            "python3 -m pip install -e '.[mcp]'"
        ) from error

    mcp = FastMCP("Aksi")

    @mcp.tool
    def scan_repo(repo_path: str, output_dir: str = "Files") -> dict[str, Any]:
        """Build symbols.json and index.json for a repository."""
        return mcp_tools.scan_repo(repo_path=repo_path, output_dir=output_dir)

    @mcp.tool
    def search_symbols(query: str, symbols_path: str = "Files/symbols.json") -> list[dict[str, Any]]:
        """Search indexed symbols by keyword."""
        return mcp_tools.search_symbols(query=query, symbols_path=symbols_path)

    @mcp.tool
    def get_context(
        path: str,
        repo_path: str,
        symbols_path: str = "Files/symbols.json",
    ) -> dict[str, Any]:
        """Return raw source code and metadata for a file path."""
        return mcp_tools.get_context(path=path, repo_path=repo_path, symbols_path=symbols_path)

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
