# Aksi Agent Instructions

## Purpose

Aksi turns a local codebase into a generated visual map for coding agents and humans.

Aksi scans locally. The scanner and graph builder are the source of truth for files, symbols, imports, dependency edges, stale state, unused-code hints, and local architecture/runtime candidates. Do not use an LLM to guess or replace those facts.

## Required MCP Flow

When a user asks to visualize, refresh, inspect, or explain a project through Aksi MCP:

1. Call `generate_visualization(path, prepare_summary_targets=True)` for the target repository.
2. Inspect `summary_mode`, `summary_completion`, and `summary_worklist` from that response.
3. Treat `summary_worklist` as the executable queue. Do not iterate `summary_targets` directly for required work.
4. If `summary_completion.required` is `true`, process every item in `summary_worklist`:

```text
for target in summary_worklist:
  context = get_context(target.node_id, path)
  summary = write_summary_from_context(context)
  save_summary(target.node_id, summary, path)
```

5. If any summaries were saved, re-check with `get_summary_worklist(path)` or `generate_visualization(path, prepare_summary_targets=True)`.
6. Use the refreshed `summary_completion` for the final status. If no summary work was required, use the original `summary_completion`.
7. Give the user the `viewer_http_url` from the latest `generate_visualization` response when it exists; otherwise give `viewer_url`. If the re-check used `get_summary_worklist(path)`, reuse the URL from the prior `generate_visualization` response. Include an accurate status:
   - if `summary_mode` is `host_llm_worklist` and refreshed `summary_completion.complete` is `true`, say the graph and saved rectangle summaries are current;
   - if `summary_mode` is `disabled`, say the graph is ready without summary targets;
   - if refreshed `summary_completion.required` is `true`, say this is an early graph-only preview and summaries are still pending.

Never present the viewer as complete while `summary_completion.required` is `true`. A generated `Files/index.html` means the graph exists; it does not mean rectangle summaries are finished.

You may share an early preview link before summary work is complete only if it is clearly labeled as graph-only/summaries-pending. Do not let an early preview replace the summary work unless the user explicitly asks to skip summaries.

Do not ask the user to run `aksi.py` manually when MCP tools are available.

## Summary Contract

`generate_visualization`:

- scans the repo locally;
- writes `Files/architecture.json`;
- preserves saved summaries and marks changed context stale;
- writes `Files/index.html` with the current graph and any saved summaries;
- returns `summary_targets` grouped by viewer area;
- returns a deduplicated `summary_worklist` containing only missing or stale nodes;
- returns `summary_completion` describing whether host-written summary work remains.

Aksi does not call an LLM and does not write summaries by itself. `summarize=True` is only a compatibility name for preparing host work items. Prefer `prepare_summary_targets=True` in MCP clients.

Each `summary_targets` item includes `summary_status`, `needs_summary`, and `action`; `summary_worklist` contains the missing or stale items that must be executed:

```text
missing -> action: write
stale   -> action: refresh
fresh   -> action: skip
```

On the first run, process every item in `summary_worklist`. On later runs, process every returned worklist item; fresh summaries are preserved and omitted from the worklist.

`save_summary` stores the host-written summary under `Files/context/`, updates `Files/context/index.json`, and regenerates `Files/index.html`. Only `save_summary` clears summary work; saving refined architecture or runtime models does not remove items from `summary_worklist`.

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

Write summaries only from `get_context` output. Keep them concise and grounded. Use low confidence when context is partial, such as a component where files were omitted.

## Viewer Coverage

`summary_targets` is view-keyed:

- `structure`: repo, folder, file, and symbol rectangles.
- `architecture`: local architecture component rectangles.
- `runtime`: static dependency-flow file/external rectangles, not traced runtime execution.

Runtime targets currently reflect the dependency-flow projection. They are not proof of traced runtime behavior.

Use `get_context(node_id, path)` before explaining any specific rectangle. Use `get_map(path)` only when you need graph details such as node IDs, counts, edges, stale files, unused markers, or architecture components.

## Architecture and Runtime Refinement

Architecture and Runtime Flow tabs start with local Aksi candidates. The host LLM may synthesize or refine labels and grouping only after grounding them in `get_map` and relevant `get_context` output:

- `save_architecture_model(model, path)` for a project architecture model.
- `save_runtime_model(model, path)` for a runtime/input-flow model.

Saved host-refined models are preferred by the viewer. Local components and dependency flow remain fallback candidates. Refined models are optional and are not a substitute for processing `summary_worklist`; only `save_summary` clears summary work.

Mark uncertainty in refined models. Do not add unsupported components, flows, callers, dependencies, or runtime behavior.

## Generated Output

Aksi writes generated files into the scanned repository:

- `Files/architecture.json`
- `Files/index.html`
- `Files/.aksi_cache*`
- `Files/context/*.json`

Do not commit `Files/`.

## MCP Tools

- `generate_visualization(path=".", summarize=True, prepare_summary_targets=None, serve_viewer=True)`
- `get_summary_worklist(path=".")`
- `get_context(node_id, path=".")`
- `save_summary(node_id, summary, path=".")`
- `get_map(path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`
- `save_architecture_model(model, path=".")`
- `save_runtime_model(model, path=".")`
- `get_models(path=".")`
- `stop_viewer(path=".")`
- `scan_repo(path=".")`

Passing `summarize=False` or `prepare_summary_targets=False` disables summary targets and makes `summary_completion.required` false. Do this only when the user explicitly wants a graph without host-written summaries.

## Project Rules

- Do not read old git history unless the user explicitly asks.
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
