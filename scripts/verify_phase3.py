from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aksi import mcp_tools
from aksi.mcp_server import create_server


async def verify_fastmcp_connection() -> bool:
    try:
        from fastmcp import Client
    except ImportError:
        print("FastMCP not installed; skipped in-memory MCP client connection.")
        return False

    server = create_server()
    client = Client(server)
    async with client:
        await client.ping()
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert {"scan_repo", "search_symbols", "get_context"}.issubset(tool_names), tool_names
    print("FastMCP in-memory client connection verified.")
    return True


def main() -> None:
    repo = Path("tests/fixtures/polyglot")
    output_dir = Path("Files")

    scan_result = mcp_tools.scan_repo(str(repo), str(output_dir))
    assert scan_result["files"] == 2, scan_result
    assert scan_result["edges"] == 2, scan_result

    search_result = mcp_tools.search_symbols("buildMessage", str(output_dir / "symbols.json"))
    assert search_result, search_result
    assert search_result[0]["path"] == "web/message.js", search_result

    context = mcp_tools.get_context(
        path="web/message.js",
        repo_path=str(repo),
        symbols_path=str(output_dir / "symbols.json"),
    )
    assert "export function buildMessage" in context["code"], context
    assert context["metadata"]["language"] == "javascript", context
    assert context["stale"] is False, context

    connected = asyncio.run(verify_fastmcp_connection())
    print("Phase 3 verified tool surface:")
    print(f"scan_repo -> {scan_result}")
    print(f"search_symbols -> {len(search_result)} match(es)")
    print(f"get_context -> {context['path']} stale={context['stale']}")
    if connected:
        print("Phase 3 verified: MCP client connected and listed Aksi tools.")
    else:
        print("Phase 3 functional gate passed; install FastMCP to run the MCP connection gate.")


if __name__ == "__main__":
    main()
