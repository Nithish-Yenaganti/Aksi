# Aksi Agent Instructions

## Mission

Aksi is a local, private codebase visualization tool. It scans source code, builds a structural architecture map, exposes that map through an MCP server, and renders it in a zoomable browser UI.

Agents working in this repo should preserve the core idea: structural truth comes from local static analysis, not from AI guesses.

## Current Architecture

- `scanner.py` scans repositories, extracts symbols/imports, computes file hashes, and writes cache data under `Files/`.
- `graph.py` converts scanner output into `Files/architecture.json`.
- `mcp_server.py` exposes `scan_repo`, `get_map`, and `get_context` through FastMCP stdio.
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
  - MCP tools: `scan_repo`, `get_map`, `get_context`

## Testing

Before finishing implementation work, run:

```bash
.venv/bin/python -m pytest
```

For quick smoke checks, also use:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py
.venv/bin/python graph.py .
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
