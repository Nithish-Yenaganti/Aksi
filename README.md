# Aksi

Aksi is a local "Glass Blueprint" tool for turning source code into a zoomable architecture map. It scans a repository with Tree-sitter, writes a static `Files/architecture.json`, exposes that map through a FastMCP stdio server, and renders it with a standalone D3 viewer.

The scanner is local-first: no external LLM APIs are used for indexing or relationship discovery.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

The current MVP expects:

- `fastmcp`
- `tree-sitter`
- `tree-sitter-python`
- `pytest` for tests

For full Tree-sitter parsing across JavaScript, TypeScript, and other languages, install the optional grammar bundle on a supported Python version:

```bash
pip install -e ".[multilang]"
```

The scanner automatically uses `tree-sitter-languages` when it is available. Without it, Python still uses Tree-sitter and JavaScript/TypeScript imports and symbols use conservative text fallbacks.

## Scan a Repository

The easiest way to run Aksi is:

```bash
python aksi.py
```

That single command scans the current repo, writes `Files/architecture.json`, starts a local static server, and prints the UI URL.

Common shortcuts:

```bash
python aksi.py --scan-only
python aksi.py --test
python aksi.py /path/to/repo --port 8080
```

The lower-level graph command is still available:

```bash
python graph.py /path/to/repo
```

This writes:

```text
/path/to/repo/Files/architecture.json
/path/to/repo/Files/.aksi_cache*
```

`Files/` is generated output and should stay ignored by git.

## Run the MCP Server

```bash
python mcp_server.py
```

To set up the local venv and generate a client-ready MCP config snippet:

```bash
scripts/setup_mcp.sh
```

To write the snippet to an ignored local file:

```bash
scripts/setup_mcp.sh --write-config .mcp/aksi.json
```

On macOS, this can also merge Aksi into Claude Desktop's config:

```bash
scripts/setup_mcp.sh --claude-desktop
```

Available tools:

- `generate_visualization(path: str = ".")`
- `scan_repo(path: str = ".")`
- `get_map(path: str = ".")`
- `get_context(node_id: str, path: str = ".")`
- `save_summary(node_id: str, summary, path: str = ".")`
- `get_summary(node_id: str, path: str = ".")`
- `list_summaries(path: str = ".")`

Normal MCP workflow:

1. The user asks their LLM host to add or inspect the visualization.
2. The host calls `generate_visualization`; users do not need to run `aksi.py`.
3. The host calls `get_context` for exact source before writing any explanation.
4. The host writes the summary and calls `save_summary`.
5. Aksi stores summaries under `Files/context/` with file hashes, so `get_summary` can report stale summaries after source changes.

## View the Map

The one-command runner already scans and serves the UI:

```bash
python aksi.py
```

For manual static serving after a scan, serve the repository directory and open the UI:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/ui/
```

The viewer loads `../Files/architecture.json`, draws the Structure and Runtime Flow diagrams, and shows saved LLM summaries from `Files/context/index.json` when they exist.

## Development

```bash
pytest
```

Useful smoke checks:

```bash
python aksi.py --scan-only
python aksi.py --test
python -m py_compile aksi.py scanner.py graph.py mcp_server.py
```
