![Aksi](assets/Title.png)

# Aksi

Aksi is an MCP-first context freshness layer for coding agents.

It prevents agents from treating a repo visualization as complete until summaries, stale context, and Architecture/Runtime models have been refreshed from grounded local evidence.

Aksi scans code locally, tracks what changed, prepares exact context worklists for the host LLM, stores verified summaries, and releases a static blueprint viewer only when the workflow is complete.

Aksi is not a general knowledge graph, graph database, arbitrary repo query engine, or universal artifact indexer. It focuses on one workflow: help an MCP host keep repo understanding fresh, grounded, and visibly complete.

## Install For MCP

**Current setup: install from this repository.** This guide does not depend on a package named `aksi` being available from a package registry. Requires Python **3.11+**, Git, and a client that supports local MCP servers over stdio.

On macOS or Linux:

```sh
git clone https://github.com/Nithish-Yenaganti/Aksi.git
cd Aksi
scripts/setup_mcp.sh --write-config .mcp/aksi.json
cat .mcp/aksi.json
```

The script creates a local `.venv`, installs the server dependencies, and writes an MCP configuration snippet containing absolute paths to this checkout. Merge that snippet into your client's MCP configuration and restart the client. Keep the checkout in a stable location. This command does not change your client's settings itself.

The optional `scripts/setup_mcp.sh --claude-desktop` command directly updates Claude Desktop's macOS configuration. Keep a copy of an existing configuration before using that option.

### First successful call

Ask the connected MCP client to call `get_digest` with the absolute path of a small repository:

```json
{
  "path": "/absolute/path/to/your/repository"
}
```

Expect a structured repository/context status response. For a complete visualization, follow the [agent workflow](#agent-workflow) until `next_action` is `release_viewer`. A generated HTML file alone does not mean the workflow is complete.

The client launches the server; there is no standalone web dashboard to start manually. The final viewer URL comes from the completed MCP workflow.

### Editable package for development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

This installs the `aksi-mcp` entry point into `.venv/bin`. If configuring it manually, use that executable's absolute path so the client can find it outside your shell.

Optional multi-language grammar bundle:

```sh
python -m pip install -e ".[multilang]"
```

Python parsing has a dedicated grammar dependency. The optional bundle has Python-version constraints; do not assume every language has equally complete parsing support.

## The Problem

AI coding agents often stop at a partial repo scan and act as if they understand the project. That creates stale summaries, missed dependencies, weak architecture guesses, and premature "done" responses.

- Which files matter?
- What imports what?
- What changed since the last scan?
- Which summaries are stale?
- What context should the agent read before editing?
- Which architecture/runtime model is still just a local guess?

Aksi turns that repo-discovery work into a local, reusable context layer.

## Aksi's Wedge

Aksi is built around a completion contract:

- scan local structure deterministically;
- detect stale summaries and changed files;
- give the host LLM exact context batches;
- save host-written summaries and refined models;
- withhold the final viewer link until the workflow is complete.

## What Aksi Does

- Scans local repositories for files, symbols, imports, dependency edges, stale files, and possible unused-code hints.
- Generates a static blueprint viewer only as the final inspection surface for the completed MCP workflow.
- Adds human-facing viewer tools: search, status filters, SVG/PNG export, and copyable node summaries.
- Exposes MCP tools for agents to fetch exact repo, file, folder, symbol, component, and runtime-flow context.
- Preserves summaries and marks only changed context as stale.
- Provides `get_digest()` as a fast first call for agents.
- Provides `get_model_seed()` so the host LLM can refine Architecture and Runtime models from grounded evidence.

Aksi does **not** call an LLM or upload code itself. The host LLM writes summaries and refined models using context returned by Aksi. A cloud-backed host may send that context to its model provider; local scanning alone does not make the entire host workflow offline.

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

- `summarize_batch`: call `get_context_batch` for `recommended_batch.node_ids`, write grounded summaries, then `save_summaries`.
- `refresh_graph`: rerun `generate_visualization`, then check workflow status again.
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

Use the source setup above today. A future registry release can support `pipx` or `uv tool` installation; document and verify the published package name and version before recommending it.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local checks and bug-report guidance. The repository's [agent instructions](AGENTS.md) describe the completion contract and model-grounding requirements.
