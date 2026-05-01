![Aksi](assets/Title.png)

# Aksi

Aksi is a local MCP context engine that helps AI coding agents understand repositories without rereading every file.

It scans code locally, builds a visual repo map, tracks stale context, stores host-written summaries, and gives agents precise node-level context through MCP.

## Why Aksi Exists

AI coding agents are powerful, but they still waste context and time rediscovering the same repository structure:

- Which files matter?
- What imports what?
- What changed since the last scan?
- Which summaries are stale?
- What context should the agent read before editing?
- Which architecture/runtime model is still just a local guess?

Aksi turns that repo-discovery work into a local, reusable context layer.

## What Aksi Does

- Scans local repositories for files, symbols, imports, dependency edges, stale files, and possible unused-code hints.
- Generates a static blueprint viewer with Structure, Architecture, and Runtime Flow tabs.
- Adds human-facing viewer tools: search, status filters, SVG/PNG export, and copyable node summaries.
- Exposes MCP tools for agents to fetch exact repo, file, folder, symbol, component, and runtime-flow context.
- Preserves summaries and marks only changed context as stale.
- Provides `get_digest()` as a fast first call for agents.
- Provides `get_model_seed()` so the host LLM can refine Architecture and Runtime models from grounded evidence.

Aksi does **not** call an LLM and does **not** upload code. The host LLM writes summaries and refined models using context returned by Aksi.

Unused-code markers are conservative static-analysis hints, not proof that code can be deleted.

## Mental Model

```text
Local repo
  -> Aksi scanner
  -> architecture.json + summary index + static viewer
  -> MCP tools
  -> host LLM reads exact context
  -> summaries and refined models are saved back into Files/context/
```

Aksi does the local mapping and memory work. The host LLM does the language and judgment work.

## Install For MCP

Aksi is meant to be launched by an MCP client, not run manually as a daily tool.

After publishing, install it as a local MCP server:

```bash
pipx install aksi
```

or:

```bash
uv tool install aksi
```

During local development, install from this checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Optional multi-language grammar bundle:

```bash
pip install -e ".[multilang]"
```

## MCP Setup

MCP clients should launch:

```text
command: aksi-mcp
```

For local development before publishing, generate a config snippet from this checkout:

```bash
scripts/setup_mcp.sh --write-config .mcp/aksi.json
```

For Claude Desktop on macOS during local development:

```bash
scripts/setup_mcp.sh --claude-desktop
```

## Agent Workflow

The user should only need to ask their MCP-enabled coding agent to use Aksi. The agent owns the workflow.

Agents should start small:

```text
get_digest(path)
```

Then, when the user wants the full visualization workflow:

```text
generate_visualization(path, prepare_summary_targets=True, response_mode="compact")
get_workflow_status(path, response_mode="compact")
```

Follow `next_action`:

- `summarize_batch`: call `get_summary_context_bundle`, write grounded summaries, then `save_summaries`.
- `refine_models`: call `get_model_seed`, inspect context as needed, then save Architecture/Runtime models.
- `release_viewer`: share `viewer.viewer_http_url` or `viewer.viewer_url`.

The viewer link is intentionally withheld until summaries and required model refinement are complete. A generated `Files/index.html` means the graph exists; it does not mean the full workflow is complete.

## Viewer

The viewer is a static inspection surface, not an in-browser chat app.

It supports:

- Structure, Architecture, and Runtime Flow tabs
- search by file, symbol, path, type, language, or saved summary text
- filters for stale, unused, and missing-summary nodes
- SVG export
- PNG export
- copy selected node summary

The viewer is generated and released by the MCP workflow. Users should not need to run a separate viewer command.

## Generated Files

Aksi writes generated artifacts into the scanned repository:

```text
Files/architecture.json
Files/index.html
Files/.aksi_cache*
Files/context/index.json
Files/context/*.json
Files/context/models.json
```

Do not commit `Files/`.

## MCP Tools

- `get_digest(...)`
- `generate_visualization(...)`
- `get_workflow_status(...)`
- `get_model_seed(...)`
- `get_summary_worklist(...)`
- `get_context(...)`
- `get_context_batch(...)`
- `get_summary_context_bundle(...)`
- `save_summaries(...)`
- `save_architecture_model(...)`
- `save_runtime_model(...)`
- `get_map(...)`
- `stop_viewer(...)`

Use `response_mode="compact"` for normal agent loops. Use full responses only when complete target, worklist, or schema payloads are needed.

## Deployment

The recommended distribution is a Python package, not a hosted scanner. Aksi needs direct filesystem access to the user's repository, so the MCP server should run beside the codebase.

Recommended install shape is `pipx install aksi` or `uv tool install aksi`, then configure the MCP client to launch `aksi-mcp`.

For a cloud product, use a hybrid model:

- local machine or user dev container: scanner, MCP server, generated viewer
- cloud: docs, releases, package metadata, optional static viewer hosting

Do not send private repositories to a central Aksi service unless the user explicitly opts into that architecture.

## Development

Run checks:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```

Packaging notes:

- `pyproject.toml` exposes `aksi-mcp` as the user-facing command.
- The viewer template is packaged as `share/aksi/ui/index.html`.
- `mcp_server.py` can load the viewer from either a repo checkout or installed package data.
