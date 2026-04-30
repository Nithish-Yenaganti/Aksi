# Aksi

## The Problem

Coding agents waste time and tokens rereading whole repositories. Humans also need a fast way to see what a codebase contains, what depends on what, what changed, and which parts need explanation.

Most repo-understanding tools either send code to a remote service, produce static docs that go stale, or make the LLM guess architecture from partial context.

## How Aksi Solves It

Aksi scans the repository locally, builds a visual map, and exposes precise MCP tools to the host agent.

- Local scanner finds files, symbols, imports, stale files, and unused-code hints.
- Static viewer renders Structure, Architecture, and Runtime Flow tabs.
- MCP tools let the host fetch only needed context instead of reading everything.
- Host LLM writes summaries and refined Architecture/Runtime models from exact Aksi context.
- Saved summaries are reused; only missing or stale nodes are refreshed later.

Aksi does not call an LLM or upload code. It runs locally and writes generated files under `Files/`.

## Install The MCP

From this repo:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Generate a local MCP config snippet:

```bash
scripts/setup_mcp.sh --write-config .mcp/aksi.json
```

For Claude Desktop on macOS:

```bash
scripts/setup_mcp.sh --claude-desktop
```

Manual MCP command:

```bash
python mcp_server.py
```

Installed command:

```bash
aksi-mcp
```

Optional multi-language grammar bundle:

```bash
pip install -e ".[multilang]"
```

## Agent Workflow

Agents should use the compact workflow:

```text
generate_visualization(path, prepare_summary_targets=True, response_mode="compact")
get_workflow_status(path, response_mode="compact")
```

Then follow `next_action`:

- `summarize_batch`: call `get_summary_context_bundle`, write summaries, then `save_summaries`.
- `refine_models`: call `get_model_seed`, inspect context as needed, then save Architecture/Runtime models.
- `release_viewer`: share `viewer.viewer_http_url` or `viewer.viewer_url`.

The viewer link is intentionally withheld until summaries and required model refinement are complete.

## Local UI

Run directly:

```bash
python aksi.py
```

Installed command:

```bash
aksi
```

Useful options:

```bash
python aksi.py --scan-only
python aksi.py --no-summarize
python aksi.py --test
python aksi.py /path/to/repo --port 8080
```

Generated output:

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

- `generate_visualization(...)`
- `get_workflow_status(...)`
- `get_model_seed(...)`
- `get_summary_worklist(...)`
- `get_context(...)`
- `get_context_batch(...)`
- `get_summary_context_bundle(...)`
- `save_summary(...)`
- `save_summaries(...)`
- `save_architecture_model(...)`
- `save_runtime_model(...)`
- `get_map(...)`
- `get_summary(...)`
- `list_summaries(...)`
- `get_models(...)`
- `stop_viewer(...)`
- `scan_repo(...)`

Use `response_mode="compact"` for normal agent loops. Use full responses only when complete target/worklist/schema payloads are needed.

## Deployment

The recommended public distribution is a Python package, not a hosted scanner. Aksi needs direct filesystem access to the user's repo, so the MCP server should run beside the codebase through `aksi-mcp`.

For easy install:

```bash
pipx install aksi
```

or:

```bash
uv tool install aksi
```

Then users configure their MCP client to run:

```text
command: aksi-mcp
```

For a cloud product, use a hybrid design: keep the scanner/MCP worker local or inside the user's own development container, and host only documentation, package downloads, release metadata, and optional static viewer hosting. Do not send private repositories to a central Aksi server unless the user explicitly opts into that architecture.

## Development

Run checks:

```bash
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```

Packaging notes:

- `pyproject.toml` defines `aksi` and `aksi-mcp`.
- The viewer template is packaged as `share/aksi/ui/index.html`.
- `mcp_server.py` can load the viewer from either repo checkout or installed package data.
