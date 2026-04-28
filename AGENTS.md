# Aksi Agent Instructions

## Mission

Aksi is a local, private codebase visualization tool. It scans source code, builds a structural architecture map, exposes that map through an MCP server, and renders it in a zoomable browser UI.

Agents working in this repo should preserve the core idea: structural truth comes from local static analysis, not from AI guesses.

## Current Architecture

- `scanner.py` scans repositories, extracts symbols/imports, computes file hashes, and writes cache data under `Files/`.
- `graph.py` converts scanner output into `Files/architecture.json`.
- `mcp_server.py` exposes visualization, context, and summary-memory tools through FastMCP stdio.
- `aksi.py` is the one-command local runner for scanning, testing, and launching the static UI.
- `ui/index.html` renders the generated architecture map with D3.
- `tests/` contains pytest coverage for scanner, graph, and MCP helper behavior.

## Development Rules

- Do not read or depend on old git history unless the user explicitly asks.
- Treat `Files/` as generated output. Do not commit generated architecture/cache files.
- Keep indexing local and private. Do not add external LLM calls for scanning, graph construction, or relationship detection.
- Prefer Tree-sitter or structured parsing for source analysis. Use regex fallbacks only when a grammar is unavailable.
- Keep the MCP server stdio-based. Do not add FastAPI, Flask, or a web service layer for the bridge.
- Keep the viewer static. `ui/index.html` should load local generated artifacts and remain easy to open from a simple static server.
- Keep public interfaces stable unless the user asks for a breaking change:
  - `python scanner.py /path/to/repo`
  - `python graph.py /path/to/repo`
  - `python mcp_server.py`
  - `python aksi.py`
  - MCP tools: `generate_visualization`, `scan_repo`, `get_map`, `get_context`, `save_summary`, `get_summary`, `list_summaries`

## MCP Agent Workflow

When a user asks an AI host/agent to add, refresh, or inspect visualization for a project, the agent should use the MCP tools instead of asking the user to run `aksi.py` manually.

Recommended orchestration:

1. Call `generate_visualization(path=".")` to scan the current repository and write `Files/architecture.json`.
2. Call `get_map(path=".")` to inspect the generated repo/folder/file/symbol graph.
3. For any rectangle/node that needs explanation, call `get_context(node_id, path=".")` first. Summaries must be based on the exact source returned by this tool, not guesses from node names.
4. The LLM host writes the human-readable summary. Aksi itself must not call external LLM APIs.
5. Call `save_summary(node_id, summary, path=".")` to persist the explanation under `Files/context/`.
6. Use `get_summary(node_id, path=".")` or `list_summaries(path=".")` before re-summarizing. If a summary is marked stale, refresh it from `get_context`.

Summary data should explain:

- what the node is
- why it exists
- how it works
- its role in the project
- important dependencies or neighbors when useful

Saved summaries are generated output and stay under ignored `Files/context/`. They include file hashes so agents can detect stale explanations after code changes.

## Testing

Before finishing implementation work, run:

```bash
.venv/bin/python -m pytest
```

For quick smoke checks, also use:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py
.venv/bin/python aksi.py --scan-only
```

If dependencies are missing, install the project in editable mode:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

## Dependency Notes

This repo may run on Python versions where `tree-sitter-languages` is unavailable. The scanner should gracefully use available Tree-sitter grammars and conservative fallbacks rather than failing the whole scan.

Use the optional multi-language dependency only when supported:

```bash
.venv/bin/python -m pip install -e '.[multilang]'
```
