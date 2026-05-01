# Aksi Agent Instructions

## Purpose

Aksi turns a local repository into a generated visual map for coding agents and humans.

Aksi owns local facts: files, folders, symbols, imports, dependency edges, stale state, unused-code hints, and local Architecture/Runtime candidates. Unused-code hints are review signals, not proof of dead code. Do not ask an LLM to replace local facts.

The host LLM owns language work: summaries, explanations, and final refined Architecture/Runtime models.

The viewer is a static inspection surface with search, filtering, and export affordances. Do not add or depend on an in-viewer chat feature; agents interact through MCP.

## Required MCP Flow

When a user asks to visualize, refresh, inspect, or explain a project through Aksi MCP:

1. Call `get_digest(path)` first for a fast repo/status/next-step overview.
2. Call `generate_visualization(path, prepare_summary_targets=True, response_mode="compact")`.
3. Call `get_workflow_status(path, response_mode="compact")`.
4. Follow `next_action`.

If `next_action` is `summarize_batch`:

1. Use `recommended_batch.node_ids` as the executable queue.
2. Fetch context with `get_summary_context_bundle(path, limit=...)` or `get_context_batch(path=path, limit=...)`.
3. Write summaries only from the returned context.
4. Verify every summary matches the node name, node type, path, source, symbols, edges, neighbors, dependencies, and context limits.
5. Save verified summaries with `save_summaries(items, path)`.
6. Call `get_workflow_status(path, response_mode="compact")` again.

If `next_action` is `refine_models`:

1. Call `get_model_seed(path)`.
2. Add detail with `get_map(path)` and targeted `get_context_batch(...)` or `get_context(...)` calls when needed.
3. Build only grounded Architecture and Runtime models.
4. Save with `save_architecture_model(model, path)` and/or `save_runtime_model(model, path)` according to the workflow status.
5. Call `get_workflow_status(path, response_mode="compact")` again.

If `next_action` is `release_viewer`:

1. Give the user `viewer.viewer_http_url` when present.
2. Otherwise give `viewer.viewer_url`.

Do not stop at `viewer_file`. A generated `Files/index.html` means the graph exists; it does not mean summaries and refined models are complete.

## Completion Contract

The whole MCP workflow is complete only when:

- summary work is complete, or summaries were explicitly disabled by the user;
- `model_refinement.complete` is `true`;
- `get_workflow_status(...).next_action` is `release_viewer`.

Do not tell the user the Aksi visualization is complete before that state.

Preview links are allowed only when the user explicitly asks to skip the full workflow. If sharing a preview, state which summaries or model refinements remain incomplete.

## Summary Contract

Aksi does not call an LLM and does not write summaries by itself.

`summarize=True` is a compatibility name for preparing host work items. Prefer `prepare_summary_targets=True` in MCP clients.

Summary status meanings:

```text
missing -> action: write
stale   -> action: refresh
fresh   -> action: skip
```

Use `summary_worklist` or `recommended_batch.node_ids` as the executable queue. Do not iterate raw `summary_targets` for required work.

`save_summaries` stores host-written summaries under `Files/context/`, updates `Files/context/index.json`, and regenerates `Files/index.html` once for the batch.

Only summary saves clear summary work. Saving Architecture or Runtime models does not clear `summary_worklist`.

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

Do not copy summaries between nodes. Use low confidence when context is partial.

## Architecture And Runtime Contract

`Structure` is the concrete local graph.

`Architecture` and `Runtime Flow` start as local candidates produced from the graph. The host LLM may refine them only after grounding in the stronger `get_model_seed`, `get_map`, and relevant context. The viewer must distinguish local candidates from host-refined models and prefer refined models only when fresh.

`Runtime Flow` is not traced execution. Treat it as a static dependency/input-flow model unless source context proves more.

`get_model_seed` should include enough compact local evidence for refinement: component candidates, entrypoints, dependency clusters, stale/refinement status, representative nodes, imports, and summary availability.

Saved refined models include a source graph hash. If the graph changes, `model_refinement.stale_models` marks saved models stale and the host must refresh them.

## Tool Surface

- `get_digest(path=".")`
- `generate_visualization(path=".", summarize=True, prepare_summary_targets=None, serve_viewer=True, response_mode="compact|full")`
- `get_workflow_status(path=".", limit=None, prepare_summary_targets=True, response_mode="compact|full")`
- `get_model_seed(path=".")`
- `get_map(path=".")`
- `get_summary_worklist(path=".")`
- `get_context(node_id, path=".")`
- `get_context_batch(node_ids=None, path=".", limit=None, include_source=True)`
- `get_summary_context_bundle(path=".", limit=None, include_source=True)`
- `save_summaries(items, path=".")`
- `save_architecture_model(model, path=".")`
- `save_runtime_model(model, path=".")`
- `stop_viewer(path=".")`

Prefer `response_mode="compact"` for normal agent loops. Use full responses only when complete targets, complete worklists, schemas, or long workflow text are needed.

If the user explicitly wants a graph without host-written summaries, pass `prepare_summary_targets=False` to both `generate_visualization` and `get_workflow_status`.

## Generated Output

Aksi writes generated files into the scanned repository:

```text
Files/architecture.json
Files/index.html
Files/.aksi_cache*
Files/context/index.json
Files/context/*.json
Files/context/models.json
```

Do not commit `Files/`.

## Project Rules

- Do not read old git history unless the user explicitly asks.
- Keep scanning, graph building, stale detection, unused-code detection, and local Architecture/Runtime candidate detection local.
- Keep the MCP server stdio-based.
- Keep the viewer static.
- Keep the viewer focused on graph inspection: search, filtering, export, summaries, and models. Do not add chat.
- Prefer Tree-sitter or structured parsing; regex fallbacks are only for resilience.
- Keep public command and MCP tool names stable unless the user asks for a breaking change.

## Main Files

- `scanner.py`: walks repos, hashes files, extracts symbols, and extracts imports.
- `graph.py`: builds `architecture.json`, nodes, dependency edges, stale flags, unused hints, and local components.
- `mcp_server.py`: FastMCP stdio server and agent-facing tools.
- `aksi.py`: developer/debug runner only; normal user workflows must go through MCP.
- `ui/index.html`: static viewer template copied into generated output.
- `tests/`: scanner, graph, MCP, summary, model, and viewer-template coverage.

## Required Checks

Before finishing implementation work, run:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```
