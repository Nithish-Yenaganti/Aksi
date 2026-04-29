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

- `generate_visualization(path: str = ".", summarize: bool = True, serve_viewer: bool = True)`
- `scan_repo(path: str = ".")`
- `get_map(path: str = ".")`
- `get_context(node_id: str, path: str = ".")`
- `save_summary(node_id: str, summary, path: str = ".")`
- `get_summary(node_id: str, path: str = ".")`
- `list_summaries(path: str = ".")`
- `save_architecture_model(model, path: str = ".")`
- `save_runtime_model(model, path: str = ".")`
- `get_models(path: str = ".")`
- `stop_viewer(path: str = ".")`

`generate_visualization` also writes a ready local viewer. It returns a localhost URL when Aksi can start the small static viewer server, and always returns a `file://` fallback:

```text
/path/to/repo/Files/index.html
http://127.0.0.1:<port>/index.html
file:///path/to/repo/Files/index.html
```

Normal MCP workflow:

1. The user asks their LLM host to add or inspect the visualization.
2. The host calls `generate_visualization(path, summarize=True, serve_viewer=True)`; users do not need to run `aksi.py`.
3. The host gives the user `viewer_http_url` when present, otherwise `viewer_url`.
4. The response includes `summary_targets` grouped by `structure`, `architecture`, and `runtime`.
5. For each target where `needs_summary` is `true`, the host calls `get_context` and uses its own LLM to write the summary.
6. The host calls `save_summary` for each written explanation so the viewer can show it when that rectangle is clicked.
7. Aksi stores summaries under `Files/context/`, updates `Files/context/index.json`, and regenerates `Files/index.html`.
8. On the next run, Aksi preserves fresh summaries, marks changed context as stale, and returns only stale or missing targets as needing work.

Aksi never calls an external LLM directly. It scans, builds the graph, detects stale files, marks unused-code hints, returns summary targets, preserves saved summaries, and writes the UI locally. The connected host LLM owns the language-writing step. To skip summary targets for a local run, use `python aksi.py --no-summarize`.

On the first run, the host should summarize every target where `needs_summary` is `true`. On later runs, the host should only summarize targets marked `missing` or `stale`; targets marked `fresh` can be skipped.

Host summary loop:

```text
for view in ["structure", "architecture", "runtime"]:
  for target in summary_targets[view]:
    if target.needs_summary is false:
      continue
    context = get_context(target.node_id, path)
    summary = write_summary_from_context(context)
    save_summary(target.node_id, summary, path)
```

`summary_targets` maps to the viewer tabs:

- `structure`: repo, folder, file, and symbol rectangles.
- `architecture`: detected architecture component rectangles.
- `runtime`: current static dependency-flow file/external rectangles, not traced runtime execution.

The Architecture and Runtime Flow tabs start with local Aksi candidates. For final output, the host LLM should read Aksi context and save refined models with `save_architecture_model` and `save_runtime_model`; the viewer prefers those saved models when available.

Recommended summary format:

```json
{
  "summary": "One or two sentences describing this rectangle.",
  "responsibility": "The job this node owns in the project.",
  "how_it_works": "Concrete behavior grounded in get_context output.",
  "relationships": "Important callers, dependencies, child nodes, or connected modules.",
  "change_risk": "low, medium, or high, with a short reason.",
  "confidence": "high, medium, or low based on available context."
}
```

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
