# Aksi Architecture

## Purpose

Aksi is a local-first codebase visualization and MCP context tool. It scans a repository on disk, builds a static graph of files/symbols/imports, writes generated artifacts under `Files/`, and lets an MCP host add grounded summaries and refined Architecture/Runtime models.

The boundary is intentional:

- Aksi owns local structural facts.
- The host LLM owns natural-language summaries and final Architecture/Runtime interpretation.
- Generated output stays inside the scanned repo under `Files/`.
- Unused-code hints are conservative review signals, not proof that code is safe to remove.
- The static viewer supports inspection features such as search, filtering, and export; chat belongs to the MCP host, not the viewer.

## System Flow

```text
MCP host
  -> generate_visualization
  -> scanner.py
  -> graph.py
  -> Files/architecture.json + Files/index.html
  -> host summary/model loop through mcp_server.py
  -> Files/context/*.json + Files/context/models.json
  -> static UI shows current graph, summaries, and refined models
```

## Main Modules

`scanner.py`

- Walks supported source files.
- Skips generated/vendor/cache directories such as `.git`, `.venv`, `node_modules`, and `Files`.
- Computes SHA-256 file hashes.
- Extracts symbols and imports with Tree-sitter when available.
- Uses conservative fallbacks when grammars are unavailable.
- Stores scan cache data in `Files/.aksi_cache*`.

`graph.py`

- Converts scanner output into `Files/architecture.json`.
- Builds repo, folder, file, symbol, external, and component nodes.
- Resolves local imports where possible.
- Creates import/dependency edges.
- Marks stale files from hash changes.
- Adds conservative unused-file and unused-symbol hints for review.
- Builds local Architecture and Runtime candidates, not final LLM-refined models.

`mcp_server.py`

- Exposes the FastMCP stdio server.
- Generates visualizations and serves the static viewer.
- Returns compact workflow status for agents.
- Returns summary worklists and source context.
- Saves host-written summaries and refined models.
- Regenerates `Files/index.html` only on write operations such as visualization generation, summary saves, and model saves.

`ui/index.html`

- Static D3 viewer template.
- Copied into each scanned repo as `Files/index.html`.
- Supports Structure, Architecture, and Runtime Flow views.
- Provides search, filtering, and export controls for graph inspection.
- Uses saved summaries from `Files/context/index.json`.
- Uses host-refined models from `Files/context/models.json` when available.
- Falls back to local static candidates when refined models are missing or stale.
- Does not include chat; MCP clients provide the agent conversation.

`aksi.py`

- Developer/debug runner.
- Calls the same generation path as MCP.
- Serves `Files/index.html` from a local HTTP server.

## MCP Workflow

The current agent workflow is status-driven:

```text
get_digest(path)
generate_visualization(path, prepare_summary_targets=True, response_mode="compact")
get_workflow_status(path, response_mode="compact")

if next_action == "summarize_batch":
  get_summary_context_bundle(path, limit=...)
  host writes verified summaries
  save_summaries(items, path)
  repeat get_workflow_status

if next_action == "refine_models":
  get_model_seed(path)
  get_map(path) and context calls as needed
  host writes architecture/runtime models
  save_architecture_model(model, path)
  save_runtime_model(model, path)
  repeat get_workflow_status

if next_action == "release_viewer":
  share viewer.viewer_http_url or viewer.viewer_url
```

`get_digest` is the fast first call for agents. It should summarize repository shape, freshness, summary/model completion, available viewer state, and the likely next action without requiring a full context pull.

The viewer link is intentionally withheld until summaries and required model refinement are complete, unless the user explicitly asks for a graph-only preview.

## Summary System

Summaries are host-written, not Aksi-written.

The summary lifecycle is:

```text
summary_targets -> summary_worklist -> get_context/get_context_batch
-> host LLM summary -> save_summaries
-> Files/context/*.json -> Files/context/index.json -> Files/index.html
```

Fresh summaries are preserved between scans. Changed source hashes mark affected summaries stale. Later runs should process only missing or stale worklist items.

Preferred summary shape:

```json
{
  "purpose": "...",
  "behavior": "...",
  "interfaces": "...",
  "dependencies": "...",
  "used_by": "...",
  "change_risk": "...",
  "open_questions": "...",
  "confidence": "..."
}
```

## Architecture And Runtime Models

Structure is always local and concrete.

Architecture and Runtime Flow start as local candidates, then the host LLM can refine them:

- `get_model_seed(path)` returns compact local facts for refinement, including component candidates, entrypoints, dependency clusters, representative nodes, imports, stale status, and summary availability.
- `save_architecture_model(model, path)` stores the host-refined architecture.
- `save_runtime_model(model, path)` stores the host-refined runtime/input-flow model.

Saved refined models include a source graph hash. If the graph changes, Aksi marks models stale and requires refresh before the viewer is considered complete again.

Runtime Flow is not traced execution. It is a cautious dependency/input-flow model grounded in static graph facts and host context review.

The UI must make the distinction visible: Structure is local fact, Architecture/Runtime candidates are local inferences, and saved Architecture/Runtime models are host-refined interpretations when fresh.

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

`Files/` is generated output and should not be committed.

## Packaging

The project exposes one user-facing installed command:

```text
aksi-mcp
```

The viewer template is packaged as:

```text
share/aksi/ui/index.html
```

`mcp_server.py` can load the template from either a repo checkout (`ui/index.html`) or an installed package data path.

## Design Rules

- Keep structural analysis local and deterministic.
- Prefer Tree-sitter or structured parsing over regex.
- Use regex fallbacks only for resilience.
- Keep MCP transport stdio-based.
- Keep the viewer static.
- Keep chat out of the viewer; use MCP for agent interaction.
- Keep public tool names stable unless a breaking change is explicitly requested.
- Treat unused-code markers as hints, not proof.
