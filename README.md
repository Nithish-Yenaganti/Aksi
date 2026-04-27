# Aksi

Aksi is a local codebase navigator for humans and AI agents. It scans a repository, extracts structural facts from source code, builds a dependency graph, and serves a zoomable visual map of the project.

The project is built around a simple rule: structural knowledge should come from static analysis, not from model guesses.

## Why This Exists

Large codebases are hard to understand because important relationships are spread across many files:

- a function is imported in one place and defined somewhere else
- a folder structure hides the real runtime relationships
- AI assistants often need too much context before they can answer safely
- diagrams and documentation become stale as soon as code changes

Aksi solves this by producing a local, machine-readable map of the repository. The map is generated from the code itself and includes file hashes so stale data can be detected.

## The Solution

Aksi creates two main artifacts:

```text
Files/symbols.json
Files/graph.json
```

`symbols.json` is the raw index. It contains:

- file paths
- language
- SHA-256 hashes
- functions
- classes
- imports

`graph.json` is the architecture map. It contains:

- a box-in-box hierarchy: project -> folder -> file -> class/function
- dependency edges from imports to definitions
- stale flags when files change after scanning

The web viewer renders `graph.json` as a zoomable D3 map.

## Why The Name Aksi

The name `Aksi` comes from the idea of an axis: a stable reference line that helps you orient yourself in a space. A codebase can feel like a maze when you only see one file at a time. Aksi gives the project an axis: a structural map that shows where things are and how they connect.

It is short, easy to type, and feels close to the project goal: orientation, movement, and direction through code.

## What This Makes Easier

Aksi helps with:

- understanding an unfamiliar repo faster
- finding where a function or class lives
- seeing which files depend on which other files
- giving an AI assistant structured context without dumping the whole repo into a prompt
- detecting when generated maps are stale
- visually exploring code from folders down to functions

For MCP usage, this is useful because the host LLM can ask focused questions:

- scan this repo
- search for a symbol
- get the raw code and metadata for one file

That keeps context small and reduces hallucination risk.

## Current Capabilities

Implemented phases:

1. Scanner
   - walks a repo
   - extracts functions, classes, imports, and hashes
   - writes `Files/symbols.json`

2. Relational engine
   - reads `symbols.json`
   - resolves imports to definitions
   - writes `Files/graph.json`

3. MCP bridge
   - exposes `scan_repo`
   - exposes `search_symbols`
   - exposes `get_file_context`

4. Web map
   - serves a local D3 viewer
   - renders a zoomable hierarchy
   - draws dependency connection lines

5. Sync layer
   - recomputes hashes
   - marks stale files in the JSON artifacts
   - supports watchdog when installed, with a polling fallback

## Project Structure

```text
src/
├── engine/
│   ├── scanner.py
│   ├── graph.py
│   ├── sync.py
│   └── io.py
├── mcp/
│   └── server.py
└── web/
    ├── app.py
    └── static/
        ├── index.html
        └── script.js

scripts/
├── verify_phase1.py
├── verify_phase2.py
├── verify_phase3.py
├── verify_phase4.py
└── verify_phase5.py

Files/
├── symbols.json
└── graph.json
```

`Files/` is the output hub. It is generated locally and ignored by git.

## How To Use

Scan a repository:

```bash
python3 -m src.engine.scanner /path/to/repo --out Files/symbols.json
```

Build the graph:

```bash
python3 -m src.engine.graph --symbols Files/symbols.json --out Files/graph.json
```

Serve the local map:

```bash
python3 -m src.web.app --stdlib --files Files --port 8765
```

Open:

```text
http://127.0.0.1:8765/src/web/static/index.html
```

Refresh stale flags:

```bash
python3 -m src.engine.sync --symbols Files/symbols.json --graph Files/graph.json
```

Run the MCP server:

```bash
python3 -m src.mcp.server
```

## Verification

Run each gate:

```bash
python3 scripts/verify_phase1.py
python3 scripts/verify_phase2.py
python3 scripts/verify_phase3.py
python3 scripts/verify_phase4.py
python3 scripts/verify_phase5.py
```

Phase 4 starts a temporary localhost server during verification.

## Notes About Tree-sitter

The scanner is designed to use Tree-sitter through `tree-sitter-languages`. If those packages are not installed in the local Python environment, it uses a deterministic static fallback parser and records that in `symbols.json` as `parser_backend`.

This keeps the development gate runnable while still keeping Tree-sitter as the intended parsing backend.

## No External Database

Aksi keeps artifacts in the repository workspace:

- JSON for symbols and graph data
- file hashes for stale detection
- local web serving for visualization

There is no PostgreSQL, Redis, or hosted service requirement.

## Design Principle

Aksi should provide raw, inspectable structure first. AI summaries can be added later, but they should sit on top of the graph, not replace it.
