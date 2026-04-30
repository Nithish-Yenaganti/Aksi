# Aksi Agent Instructions

## Purpose

Aksi turns a local codebase into a generated visual map for coding agents and humans.

Aksi scans locally. The scanner and graph builder are the source of truth for files, symbols, imports, dependency edges, stale state, unused-code hints, and local architecture/runtime candidates. Do not use an LLM to guess or replace those facts.

## Required MCP Flow

When a user asks to visualize, refresh, inspect, or explain a project through Aksi MCP:

1. Call `generate_visualization(path, prepare_summary_targets=True)`.
2. Call `get_workflow_status(path)` and follow its `next_action`, `recommended_batch`, `viewer`, and exact `instructions`.
3. If `next_action` is `summarize_batch`, treat `summary_worklist`/`recommended_batch.node_ids` as the executable queue. Do not iterate `summary_targets` directly for required work.
4. Prefer the tool named by `recommended_batch.tool` (`get_summary_context_bundle(path)` by default) or `get_context_batch(path=path)` to fetch context for the current missing/stale worklist in one call. Use `limit` if the worklist is too large for the host context window, then repeat.
5. Write grounded summaries from the exact returned contexts, verify each summary matches its node, then call `save_summaries(items, path)` once per batch. Keep `get_context(...)` and `save_summary(...)` for targeted or backwards-compatible one-node workflows.
6. After each `save_summaries(...)` or `save_summary(...)`, call `get_workflow_status(path)` again. Continue summary batches until `next_action` changes away from `summarize_batch`.
7. If `next_action` is `refine_models`, call `get_model_seed(path)` first. Use that compact seed plus `get_map(path)` and relevant `get_context_batch(...)`/`get_context(...)` output to build grounded refined models, then call `save_architecture_model(model, path)` and/or `save_runtime_model(model, path)` according to `model.architecture_required` and `model.runtime_required`.
8. After each model save, call `get_workflow_status(path)` again. Continue until `next_action` is `release_viewer`.
9. Only when `get_workflow_status(path).next_action` is `release_viewer`, give the user `viewer.viewer_http_url` when present, otherwise `viewer.viewer_url`.

Do not ask the user to run `aksi.py` manually when MCP tools are available.

## Completion Contract

The whole MCP run is complete only when:

- summary work is complete, or summaries were explicitly disabled by the user;
- `model_refinement.complete` is `true`.

The existence of `Files/index.html`, `Files/architecture.json`, `viewer_file`, `viewer_http_url`, or `viewer_url` never overrides those state fields.

Do not tell the user "Aksi visualization is ready as a graph preview" during the normal workflow. Do not surface the viewer link as a stopping point while work remains. A preview link may be shared only if the user explicitly asks to stop before completion; in that case, state which summaries or model refinements remain incomplete.

If `viewer_url` or `viewer_http_url` is `null`, keep working from `summary_worklist` and `model_refinement`; do not treat `viewer_file` as a replacement URL.

## Summary Rules

`generate_visualization` scans the repo, writes generated files, preserves saved summaries, returns grouped `summary_targets`, and returns a deduplicated `summary_worklist` containing only missing or stale nodes.

Aksi does not call an LLM and does not write summaries by itself. `summarize=True` is only a compatibility name for preparing host work items. Prefer `prepare_summary_targets=True` in MCP clients.

Each `summary_targets` item includes `summary_status`, `needs_summary`, and `action`:

```text
missing -> action: write
stale   -> action: refresh
fresh   -> action: skip
```

`save_summaries` stores host-written summaries under `Files/context/`, updates `Files/context/index.json`, and regenerates `Files/index.html` once for the batch. `save_summary` does the same for one node. Only summary saves clear summary work; saving refined architecture or runtime models does not remove items from `summary_worklist`.

Before calling `save_summaries` or `save_summary`, verify each summary against the matching `get_context_batch`/`get_context` result. A valid summary must match the returned node name, node type, path, source, symbols, edges, neighbors, dependencies, and context limits. If it does not match, rewrite it from the same context output before saving.

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

Write summaries only from `get_context_batch`, `get_summary_context_bundle`, or `get_context` output. Use low confidence when context is partial. Do not copy summaries between nodes.

## Architecture and Runtime Rules

`summary_targets` is view-keyed:

- `structure`: repo, folder, file, and symbol rectangles.
- `architecture`: local architecture component rectangles.
- `runtime`: static dependency-flow file/external rectangles, not traced runtime execution.

Architecture and Runtime Flow tabs start with local Aksi candidates. They are useful previews, not complete host-understood models.

For a complete Aksi run, the host LLM must reanalyze Architecture and Runtime Flow from `get_model_seed`, `get_map`, and relevant `get_context_batch`/`get_context` output, write grounded summaries for their rectangles, save those summaries with `save_summaries`, and save the final refined diagrams with `save_architecture_model` and `save_runtime_model`.

`get_model_seed(path)` is the preferred starting point for refinement. It returns local component candidates, dependency-flow candidates, entrypoints, external dependencies, stale/unused hints, current model-refinement state, and recommended context nodes. It is not an LLM answer; the host LLM still writes the final Architecture and Runtime models from that seed and source context.

Aksi stores a source graph hash with each refined model. If the repo graph changes later, `model_refinement.stale_models` marks saved models stale and sets `architecture_required` or `runtime_required` back to `true`. Refresh stale models from current `get_model_seed`, `get_map`, and `get_context` output.

Mark uncertainty in refined models. Do not add unsupported components, flows, callers, dependencies, or runtime behavior.

## MCP Tools

- `generate_visualization(path=".", summarize=True, prepare_summary_targets=None, serve_viewer=True)`
- `get_workflow_status(path=".", limit=None)`
- `get_model_seed(path=".")`
- `get_summary_worklist(path=".")`
- `get_context(node_id, path=".")`
- `get_context_batch(node_ids=None, path=".", limit=None, include_source=True)`
- `get_summary_context_bundle(path=".", limit=None, include_source=True)`
- `save_summary(node_id, summary, path=".")`
- `save_summaries(items, path=".")`
- `get_map(path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`
- `save_architecture_model(model, path=".")`
- `save_runtime_model(model, path=".")`
- `get_models(path=".")`
- `stop_viewer(path=".")`
- `scan_repo(path=".")`

Passing `summarize=False` or `prepare_summary_targets=False` disables summary targets and makes `summary_completion.required` false. If you continue with `get_workflow_status` for that graph-only run, pass `prepare_summary_targets=False` there too. Do this only when the user explicitly wants a graph without host-written summaries.

## Project Rules

- Do not read old git history unless the user explicitly asks.
- Do not commit `Files/`; it is generated output.
- Keep scanning, graph building, stale detection, unused-code detection, and local architecture/runtime candidate detection local.
- Keep the MCP server stdio-based.
- Keep the viewer static.
- Prefer Tree-sitter or structured parsing; regex fallbacks are only for resilience.
- Keep public command and MCP tool names stable unless the user asks for a breaking change.

Main files:

- `scanner.py`: walks the repo, hashes files, extracts symbols, and extracts imports.
- `graph.py`: builds `architecture.json`, tree nodes, dependency edges, stale flags, unused-code hints, and local architecture components.
- `mcp_server.py`: FastMCP stdio server and agent-facing tools.
- `aksi.py`: one-command local runner that generates and serves `Files/index.html`.
- `ui/index.html`: static viewer template copied into generated output.
- `tests/`: coverage for scanner, graph, MCP behavior, and summary persistence.

Before finishing implementation work, run:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```
