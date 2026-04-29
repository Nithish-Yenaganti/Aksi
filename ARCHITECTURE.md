# Aksi Architecture Design

## Purpose

Aksi is a local, private codebase visualization tool. It scans a repository, builds a generated architecture map, exposes that map to MCP-capable AI hosts, and renders the result in a static browser UI.

The core rule is simple: structural truth comes from local static analysis, not from LLM guesses.

## System Overview

```text
User / LLM Host
      |
      v
  aksi.py or MCP tool
      |
      v
  scanner.py
      |
      v
  graph.py
      |
      v
  Files/architecture.json
      |
      +--------------------+
      |                    |
      v                    v
ui/index.html        mcp_server.py
D3 viewer            FastMCP stdio tools
```

## Main Components

### `aksi.py`

`aksi.py` is the one-command local runner.

It can:

- scan the target repository
- write `Files/architecture.json`
- run tests with `--test`
- start a local static server for the UI

This is the command normal users should run when using Aksi directly.

### `scanner.py`

`scanner.py` is the local indexing layer.

It:

- walks source files in the target repo
- skips generated and dependency directories such as `.git`, `.venv`, `node_modules`, and `Files`
- computes SHA-256 hashes per scanned file
- extracts symbols such as functions, classes, interfaces, structs, and types
- extracts imports/includes as dependency candidates
- stores hash cache data in `Files/.aksi_cache*`

Tree-sitter is preferred when available. Conservative fallback parsing is used when a language grammar is missing.

### `graph.py`

`graph.py` converts scanner output into the generated architecture map.

It builds:

- repo, folder, file, and symbol nodes
- parent-child hierarchy edges
- import/dependency edges
- external dependency nodes for unresolved imports
- stale flags when files change
- possible unused/dead-code markers

The main output is:

```text
Files/architecture.json
```

### `mcp_server.py`

`mcp_server.py` exposes Aksi through FastMCP stdio.

It lets an AI host call local tools instead of doing heavy repo analysis by itself.

Current MCP tools:

- `generate_visualization(path=".", summarize=True, prepare_summary_targets=None, serve_viewer=True)`
- `scan_repo(path=".")`
- `get_map(path=".")`
- `get_summary_worklist(path=".")`
- `get_context(node_id, path=".")`
- `save_summary(node_id, summary, path=".")`
- `get_summary(node_id, path=".")`
- `list_summaries(path=".")`
- `save_architecture_model(model, path=".")`
- `save_runtime_model(model, path=".")`
- `get_models(path=".")`
- `stop_viewer(path=".")`

The MCP server does not scan by asking an LLM. It calls Aksi’s local scanner and graph builder.

### `ui/index.html`

`ui/index.html` is the static D3 viewer.

It loads:

```text
../Files/architecture.json
../Files/context/index.json
```

It currently renders three views:

- `Structure`: full repo tree with folders, files, and symbols
- `Architecture`: host-refined project architecture when saved; otherwise local component candidates
- `Runtime Flow`: host-refined input/process flow when saved; otherwise static import/dependency-flow projection

Clicking a rectangle opens a detail card with:

- concise summary
- responsibility
- how it works
- relationships or change risk
- saved LLM summary when available

### `Files/`

`Files/` is generated output inside the scanned repository.

It may contain:

```text
Files/architecture.json
Files/.aksi_cache*
Files/context/index.json
Files/context/*.json
```

This folder should stay ignored by git.

### `tests/`

`tests/` protects scanner, graph, and MCP helper behavior.

Current test areas:

- symbol and import extraction
- ignored directory behavior
- changed/stale file detection
- folder/file/symbol graph nesting
- local import resolution
- possible unused-code markers
- MCP tool return shapes

## Data Flow

```text
1. User runs Aksi or an LLM host calls an MCP tool.
2. Aksi scans the target repo locally.
3. The scanner extracts files, hashes, symbols, and imports.
4. The graph builder creates nodes, edges, stale flags, and unused-code hints.
5. Aksi writes Files/architecture.json.
6. The UI reads architecture.json and renders visual diagrams.
7. The MCP server returns summary targets for rectangles that are missing or stale.
8. The LLM host fetches exact context for those targets with `get_context`.
9. The LLM host saves summaries back into `Files/context/`.
10. Aksi updates `Files/context/index.json` and regenerates `Files/index.html`.
```

## Generated JSON Shape

`Files/architecture.json` has this top-level shape:

```json
{
  "root": "repo:.",
  "nodes": {},
  "edges": [],
  "generated_at": "timestamp",
  "scanner": {},
  "analysis": {}
}
```

Nodes can represent:

- `repo`
- `folder`
- `file`
- `function`
- `class`
- `interface`
- `struct`
- `type`
- `external`

Edges currently represent imports/dependencies.

## Dead-Code Marking

Aksi marks possible dead code with local static-analysis hints.

Files are marked possibly unused when no local file imports them and they are not likely entrypoints.

Symbols are marked possibly unused when no local reference is found outside their declaration line.

These markers are useful for visual triage, but they are not runtime proof. Dynamic calls, framework entrypoints, decorators, plugins, reflection, shell commands, and external users can make code live even when local references are not obvious.

## MCP Agent Workflow

When connected to an MCP host, the intended workflow is:

```text
User asks host to visualize or explain a repo
      |
      v
Host calls generate_visualization(path, prepare_summary_targets=True, serve_viewer=True)
      |
      v
Aksi scans locally, preserves summaries, writes architecture.json and index.html
      |
      v
Host opens viewer URL and reads summary_targets
      |
      v
Host loops over structure, architecture, and runtime targets where needs_summary is true
      |
      v
Host writes grounded summaries
      |
      v
Host calls save_summary(node_id, summary, path)
      |
      v
User clicks rectangles and sees saved summaries
```

This keeps structural analysis local. The LLM host is used only for orchestration and grounded natural-language explanations.

The host summary loop is:

```text
for view in ["structure", "architecture", "runtime"]:
  for target in summary_targets[view]:
    if target.needs_summary is false:
      continue
    context = get_context(target.node_id, path)
    summary = write_summary_from_context(context)
    save_summary(target.node_id, summary, path)
```

## Design Principles

- Local-first and private by default
- Generated files stay under `Files/`
- The UI stays static and easy to serve
- The MCP bridge stays stdio-based
- Tree-sitter or structured parsing is preferred over loose text parsing
- LLM summaries must be grounded in exact source context from MCP tools
- Public commands and MCP tool names should remain stable
