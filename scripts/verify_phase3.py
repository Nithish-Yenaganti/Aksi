from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mcp.server import create_server, get_file_context, scan_repo, search_symbols


async def verify_fastmcp_if_available() -> bool:
    try:
        from fastmcp import Client
    except ImportError:
        print("FastMCP not installed; skipped MCP client registration check.")
        return False

    server = create_server()
    client = Client(server)
    async with client:
        await client.ping()
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert {"scan_repo_tool", "search_symbols_tool", "get_file_context_tool"}.issubset(names), names
    print("FastMCP registration verified.")
    return True


def main() -> None:
    repo = Path("tests/fixtures/phase1_repo")
    scan = scan_repo(str(repo), "Files")
    assert scan["files"] == 3, scan
    assert scan["edges"] == 2, scan

    matches = search_symbols("renderWidget", "Files/symbols.json")
    assert any(match["path"] == "web/widget.js" for match in matches), matches
    assert any(match["path"] == "pkg/service.py" for match in matches), matches

    context = get_file_context(
        "pkg/service.py",
        str(repo),
        "Files/symbols.json",
        "Files/graph.json",
    )
    assert "class Service" in context["code"], context
    assert context["summary"]["stale"] is False, context
    assert context["summary"]["outgoing_edges"], context

    connected = asyncio.run(verify_fastmcp_if_available())
    print("Phase 3 tool checks:")
    print(f"scan_repo -> {scan}")
    print(f"search_symbols -> {len(matches)} match(es)")
    print(f"get_file_context -> {context['path']} stale={context['summary']['stale']}")
    if connected:
        print("Phase 3 gate passed with FastMCP registration.")
    else:
        print("Phase 3 gate passed for tool logic; install FastMCP to verify client registration.")


if __name__ == "__main__":
    main()
