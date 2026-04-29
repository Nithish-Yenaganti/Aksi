# Aksi Agent Instructions

## Purpose

Aksi turns a local codebase into a generated visual map for coding agents and humans.

The scanner and graph builder are local source-of-truth systems. Do not use an LLM to guess files, symbols, imports, dependencies, stale state, unused-code hints, or architecture candidates.

## Expected Agent Flow

When a user asks to visualize, refresh, inspect, or explain a project through MCP:

1. Call `generate_visualization(path)` for the target repository.
2. Give the user `viewer_http_url` when it exists; otherwise give `viewer_url`.
3. Use `get_map(path)` when you need node IDs, counts, edges, stale files, unused markers, or architecture components.
4. Use `get_context(node_id, path)` before explaining any specific rectangle.
5. Use `save_summary(node_id, summary, path)` when an explanation should appear in the viewer later.

Do not ask the user to run `aksi.py` manually when MCP tools are available.

## Summary Flow

`generate_visualization` scans first, then writes summaries.

Default behavior:

```text
scan repo locally
build graph locally
detect architecture components locally
optionally call configured LLM for repo/component summaries
save summaries in Files/context/
write Files/index.html
return viewer URL
```

The LLM may only write natural-language summaries after Aksi has produced local context. The LLM must not decide source structure.

If no LLM provider or API key is configured, Aksi still generates the graph and viewer. Summary failures are returned in `llm_summary.errors`.

## Generated Output

Aksi writes generated files into the scanned repository:

- `Files/architecture.json`
- `Files/index.html`
- `Files/.aksi_cache*`
- `Files/context/*.json`

Do not commit `Files/`.

## Main Files

- `scanner.py`: walks the repo, hashes files, extracts symbols, and extracts imports.
- `graph.py`: builds `architecture.json`, tree nodes, dependency edges, stale flags, unused-code hints, and architecture components.
- `llm_summary.py`: optional LLM summary provider used only after scanning.
- `mcp_server.py`: FastMCP stdio server and agent-facing tools.
- `aksi.py`: one-command local runner that generates and serves `Files/index.html`.
- `ui/index.html`: static viewer template copied into generated output.
- `tests/`: coverage for scanner, graph, MCP behavior, and summary persistence.

## MCP Tools

- `generate_visualization(path=".", summarize=True, llm_provider=None, llm_model=None, serve_viewer=True)`
- `scan_repo(path=".")`
- `get_map(path=".")`
- `get_context(node_id, path=".")`
- `save_summary(node_id, summary, path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`

## CLI

```bash
python aksi.py
python aksi.py --no-summarize
python aksi.py --scan-only
python aksi.py --test
```

`python aksi.py` writes `Files/index.html` and serves that generated viewer.

## Rules

- Do not read old git history unless the user explicitly asks.
- Keep scanning, graph building, stale detection, unused-code detection, and architecture candidate detection local.
- Keep the MCP server stdio-based.
- Keep the viewer static.
- Prefer Tree-sitter or structured parsing; regex fallbacks are only for resilience.
- Keep public command and MCP tool names stable unless the user asks for a breaking change.

## Validation

Before finishing implementation work, run:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py llm_summary.py
.venv/bin/python -m pytest
```
