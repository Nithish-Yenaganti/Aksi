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

- `generate_visualization(path: str = ".", summarize: bool = True, llm_provider: str | None = None, llm_model: str | None = None, serve_viewer: bool = True)`
- `scan_repo(path: str = ".")`
- `get_map(path: str = ".")`
- `get_context(node_id: str, path: str = ".")`
- `save_summary(node_id: str, summary, path: str = ".")`
- `get_summary(node_id: str, path: str = ".")`
- `list_summaries(path: str = ".")`

`generate_visualization` also writes a ready local viewer. It returns a localhost URL when Aksi can start the small static viewer server, and always returns a `file://` fallback:

```text
/path/to/repo/Files/index.html
http://127.0.0.1:<port>/index.html
file:///path/to/repo/Files/index.html
```

Normal MCP workflow:

1. The user asks their LLM host to add or inspect the visualization.
2. The host calls `generate_visualization`; users do not need to run `aksi.py`.
3. The host gives the user `viewer_http_url` when present, otherwise `viewer_url`.
4. The host calls `get_context` for exact source before writing any explanation.
5. The host writes the summary and calls `save_summary`.
6. Aksi stores summaries under `Files/context/` with file hashes, so `get_summary` can report stale summaries after source changes.

Direct LLM summaries run after scanning by default:

```bash
OPENAI_API_KEY=... python aksi.py
```

Or through MCP:

```text
generate_visualization(path=".", llm_provider="openai")
```

Aksi still scans, builds the graph, detects stale files, marks unused-code hints, and writes the UI locally. The configured LLM is used only after scanning to write repo and architecture-component summaries, which Aksi stores under `Files/context/`. For tests or dry runs, use `llm_provider="mock"`. To skip summaries for a local run, use `python aksi.py --no-summarize`.

## View the Map

The one-command runner already scans and serves the UI:

```bash
python aksi.py
```

For manual static serving after a scan, serve the repository directory and open the UI:

```bash
python -m http.server 8000 --directory Files
```

Then open:

```text
http://localhost:8000/index.html
```

The source viewer template lives at `ui/index.html`. The generated viewer lives at `Files/index.html`, embeds the generated map directly, and is the file users should open.

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
