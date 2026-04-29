# Aksi Agent Instructions

## Mission

Aksi is a local, private codebase visualizer for coding agents and humans.

Agents must keep structural analysis local. Do not use an LLM to guess files, symbols, imports, dependencies, stale state, or unused-code markers. Use Aksi tools.

## If User Asks For Visualization

When connected through MCP and the user asks to visualize, refresh, inspect, or explain a project:

1. Call `generate_visualization(path)` for the target repo.
   - If the user explicitly wants Aksi to generate architecture summaries directly, call `generate_visualization(path, summarize=True)`.
   - Direct LLM summaries require an explicit opt-in and provider configuration such as `OPENAI_API_KEY`.
2. Give the user `viewer_http_url` when present. If localhost startup is unavailable, give `viewer_url`.
3. Call `get_map(path)` if you need map counts, node IDs, edges, stale files, or unused markers.
4. Call `get_context(node_id, path)` before explaining any specific rectangle.
5. Write the explanation from the exact returned source/context.
6. Call `save_summary(node_id, summary, path)` when the user wants that explanation available in the UI later.

If `summarize=True` is used, Aksi will call the configured LLM only for repo and architecture-component summaries. Scanning, graph building, stale detection, unused-code hints, and UI generation remain local.

Do not ask the user to run `aksi.py` manually when MCP tools are available.

## Generated Output

Aksi writes generated files into the scanned repo:

- `Files/architecture.json`
- `Files/index.html`
- `Files/.aksi_cache*`
- `Files/context/*.json`

`Files/index.html` is the ready viewer for that scanned repo. It embeds the generated map. `generate_visualization` tries to start a local static server and returns `viewer_http_url`; if that is unavailable, use the returned `viewer_url`.

Do not commit `Files/`.

## Core Files

- `scanner.py`: local scanner for files, hashes, symbols, and imports.
- `graph.py`: builds `Files/architecture.json`, dependency edges, stale flags, and unused-code hints.
- `mcp_server.py`: FastMCP stdio tools for agents.
- `aksi.py`: direct local runner for manual scan and UI serving.
- `ui/index.html`: source template for the generated viewer.
- `tests/`: scanner, graph, and MCP tests.

## MCP Tools

- `generate_visualization(path=".")`
- `generate_visualization(path=".", summarize=True, llm_provider="openai", llm_model=None)`
- `scan_repo(path=".")`
- `get_map(path=".")`
- `get_context(node_id, path=".")`
- `save_summary(node_id, summary, path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`

## Rules

- Do not read old git history unless the user explicitly asks.
- Do not add external LLM calls to scanning, graph building, stale detection, unused-code detection, or UI generation.
- Optional direct LLM calls are allowed only for explicit `summarize=True` architecture summaries.
- Keep the MCP server stdio-based.
- Keep the viewer static.
- Prefer Tree-sitter or structured parsing; regex fallbacks are only for resilience.
- Keep public commands and MCP tool names stable unless the user asks for a breaking change.

## Validation

Before finishing implementation work, run:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```
