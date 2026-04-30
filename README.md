# Aksi

Aksi is a local-first codebase visualization and MCP context tool. It scans a repository, builds a static blueprint of files/symbols/imports, writes a browser viewer under `Files/`, and gives MCP-capable coding agents precise context tools.

Aksi does not call an LLM. The scanner and graph builder run locally. The connected host LLM writes summaries and refined Architecture/Runtime models from Aksi-provided context.

## Install

For development from this repo:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Optional multi-language grammar bundle:

```bash
pip install -e ".[multilang]"
```

Installed commands:

```bash
aksi
aksi-mcp
```

## Local Use

Scan and serve the current repository:

```bash
python aksi.py
```

Equivalent installed command:

```bash
aksi
```

Useful variants:

```bash
python aksi.py --scan-only
python aksi.py --no-summarize
python aksi.py --test
python aksi.py /path/to/repo --port 8080
```

Aksi writes generated output into the scanned repo:

```text
Files/architecture.json
Files/index.html
Files/.aksi_cache*
Files/context/index.json
Files/context/*.json
Files/context/models.json
```

`Files/` is generated output and should stay ignored by git.

## MCP Setup

Run the stdio MCP server directly:

```bash
python mcp_server.py
```

Equivalent installed command:

```bash
aksi-mcp
```

Generate a client config snippet:

```bash
scripts/setup_mcp.sh
scripts/setup_mcp.sh --write-config .mcp/aksi.json
scripts/setup_mcp.sh --claude-desktop
```

## MCP Tools

- `generate_visualization(path=".", summarize=True, prepare_summary_targets=None, serve_viewer=True, response_mode="full")`
- `get_workflow_status(path=".", limit=None, prepare_summary_targets=True, response_mode="full")`
- `get_model_seed(path=".")`
- `scan_repo(path=".")`
- `get_map(path=".")`
- `get_summary_worklist(path=".")`
- `get_context(node_id, path=".")`
- `get_context_batch(node_ids=None, path=".", limit=None, include_source=True)`
- `get_summary_context_bundle(path=".", limit=None, include_source=True)`
- `save_summary(node_id, summary, path=".")`
- `save_summaries(items, path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`
- `save_architecture_model(model, path=".")`
- `save_runtime_model(model, path=".")`
- `get_models(path=".")`
- `stop_viewer(path=".")`

Use `response_mode="compact"` for normal agent loops. Compact mode returns counts, file paths, release state, next action, and a recommended batch without large worklist/schema payloads.

## Expected MCP Workflow

```text
generate_visualization(path, prepare_summary_targets=True, response_mode="compact")
get_workflow_status(path, response_mode="compact")
```

Then follow `next_action`:

`summarize_batch`

```text
get_summary_context_bundle(path, limit=...)
host writes and verifies summaries from returned context
save_summaries(items, path)
get_workflow_status(path, response_mode="compact")
```

`refine_models`

```text
get_model_seed(path)
get_map(path) and get_context/get_context_batch as needed
host writes grounded Architecture and Runtime models
save_architecture_model(model, path)
save_runtime_model(model, path)
get_workflow_status(path, response_mode="compact")
```

`release_viewer`

```text
share viewer.viewer_http_url when present, otherwise viewer.viewer_url
```

The viewer URL is withheld until summaries are current and required model refinement is current. A graph-only preview should be shared only when the user explicitly asks to skip the full workflow.

## Summary Rules

`summarize=True` and `prepare_summary_targets=True` prepare host work items. They do not write summaries.

The host should summarize only missing or stale worklist items. Fresh summaries are preserved and reused.

Preferred summary shape:

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

## Viewer

The source template is:

```text
ui/index.html
```

The generated viewer is:

```text
Files/index.html
```

The viewer has three tabs:

- `Structure`: repo, folders, files, and symbols from local scanning.
- `Architecture`: host-refined model when available, otherwise local component candidates.
- `Runtime Flow`: host-refined runtime/input-flow model when available, otherwise static dependency-flow candidates.

Clicking a rectangle opens a detail panel using saved summaries first, then refined model data, then local fallback text.

## Development

Run checks:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```

Build/package notes:

- `pyproject.toml` defines `aksi` and `aksi-mcp` console commands.
- The viewer template is packaged as `share/aksi/ui/index.html`.
- `mcp_server.py` can load the viewer template from either the repo checkout or installed package data.

## Privacy

Aksi scans local files and writes local generated artifacts. It does not upload code and does not call external LLM APIs.
