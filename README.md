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

- `generate_visualization(path: str = ".", summarize: bool = True, prepare_summary_targets: bool | None = None, serve_viewer: bool = True)`
- `get_workflow_status(path: str = ".", limit: int | None = None, prepare_summary_targets: bool = True)`
- `get_model_seed(path: str = ".")`
- `scan_repo(path: str = ".")`
- `get_map(path: str = ".")`
- `get_summary_worklist(path: str = ".")`
- `get_context(node_id: str, path: str = ".")`
- `get_context_batch(node_ids: list[str] | None = None, path: str = ".", limit: int | None = None, include_source: bool = True)`
- `get_summary_context_bundle(path: str = ".", limit: int | None = None, include_source: bool = True)`
- `save_summary(node_id: str, summary, path: str = ".")`
- `save_summaries(items: list[dict], path: str = ".")`
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
2. The host calls `generate_visualization(path, prepare_summary_targets=True, serve_viewer=True)`; users do not need to run `aksi.py`.
3. The host calls `get_workflow_status(path)` and follows `next_action`, `recommended_batch`, `viewer`, and the exact `instructions`.
4. Aksi withholds `viewer_http_url`/`viewer_url` until summaries and required model refinement are complete; `get_workflow_status` exposes the withheld reason and returns viewer URLs only when `next_action` is `release_viewer`.
5. If `next_action` is `summarize_batch`, the host calls the tool named by `recommended_batch.tool` (`get_summary_context_bundle` by default) or `get_context_batch(path=path)` to fetch the current missing/stale worklist in one call. Use `limit` to process huge repos in chunks.
6. The host uses its own LLM to write summaries, then verifies each summary against the exact returned node, source, symbols, edges, neighbors, and context limits; mismatches must be re-summarized before saving.
7. The host calls `save_summaries(items, path)` for verified explanations so the viewer can show them when rectangles are clicked. `save_summary` remains available for targeted one-node workflows.
8. After each summary save, the host calls `get_workflow_status(path)` again and keeps following its `next_action`.
9. If `next_action` is `refine_models`, the host starts with `get_model_seed(path)`, adds source detail from current `get_map`/`get_context_batch`/`get_context` as needed, and saves grounded models with `save_architecture_model` and/or `save_runtime_model` according to the returned model status.
10. After each model save, the host calls `get_workflow_status(path)` again. Only `release_viewer` means the viewer link is ready to share.
11. On the next run, Aksi preserves fresh summaries, marks changed context as stale, and returns only stale or missing targets as needing work.

Aksi never calls an external LLM directly. It scans, builds the graph, detects stale files, marks unused-code hints, returns summary targets, preserves saved summaries, and writes the UI locally. The connected host LLM owns the language-writing step. To skip summary targets for a local run, use `python aksi.py --no-summarize`.

`summarize=True` is a compatibility name for preparing summary targets. It does not write summaries automatically. Prefer `prepare_summary_targets=True` in new MCP clients.

If a user explicitly asks for a graph without host-written summaries, call `generate_visualization(..., prepare_summary_targets=False)` and pass `prepare_summary_targets=False` to `get_workflow_status` for that run too.

The viewer may be usable before summaries are complete. If `summary_completion.viewer_state` is `graph_ready_summaries_pending`, the host must complete `summary_worklist` before claiming Structure, Architecture, and Runtime rectangles have grounded explanations.

On the first run, the host should complete every item in `summary_worklist`. On later runs, Aksi only puts missing or stale nodes in that worklist; fresh summaries are skipped.

Host summary loop:

```text
status = get_workflow_status(path, limit=host_context_limit)
while status.next_action == "summarize_batch":
  bundle = get_summary_context_bundle(path, limit=host_context_limit)
  items = []
  for item in bundle.items:
    summary = write_summary_from_context(item.context)
    verify_summary_matches_context(summary, item.context)
    items.append({ "node_id": item.node_id, "summary": summary })
  save_summaries(items, path)
  status = get_workflow_status(path, limit=host_context_limit)
```

`summary_targets` maps to the viewer tabs:

- `structure`: repo, folder, file, and symbol rectangles.
- `architecture`: detected architecture component rectangles.
- `runtime`: current static dependency-flow file/external rectangles, not traced runtime execution.

The Architecture and Runtime Flow tabs start with local Aksi candidates. For final output, the host LLM should call `get_model_seed(path)` for a compact grounded starting point, read additional Aksi context when needed, and save refined models with `save_architecture_model` and `save_runtime_model`; the viewer prefers those saved models when available.

`get_model_seed(path)` does not call an LLM. It packages local facts for the host: component candidates, component edges, static dependency-flow edges, entrypoints, external dependencies, stale/unused hints, model-refinement status, and recommended context nodes.

`model_refinement` tells the host whether those refined models are still missing:

```json
{
  "architecture_required": true,
  "runtime_required": true,
  "complete": false,
  "source": "local_candidates_need_host_refinement"
}
```

Saved refined models include a source graph hash. If code or dependencies change, `model_refinement.stale_models` marks outdated models stale and sets the required flags back to `true`.

Recommended summary format:

```json
{
  "purpose": "What this node is for in one sentence.",
  "behavior": "What it actually does, grounded in get_context output.",
  "interfaces": "Important functions, classes, inputs, outputs, commands, or MCP tools exposed here.",
  "dependencies": "Key upstream/downstream files, modules, services, or data it relies on.",
  "used_by": "Known callers, views, workflows, or project areas that depend on it.",
  "change_risk": "low, medium, or high, with the reason a future agent should care.",
  "open_questions": "Important unknowns or cases where the source should be reopened.",
  "confidence": "high, medium, or low based on how complete the returned context was."
}
```

On later runs, the host should use saved fresh summaries as the first layer of context. It should call `get_context` only for missing, stale, low-confidence, or task-critical nodes.

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
