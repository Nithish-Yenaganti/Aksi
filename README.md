[![Project Status: WIP – Initial development is in progress, but there has not yet been a stable, usable release suitable for the public.](https://www.repostatus.org/badges/latest/wip.svg)](https://www.repostatus.org/#wip)
# 👁️ Aksi

Aksi is a high-performance, Python-based Model Context Protocol (MCP) server designed to bridge the gap between complex codebases and human/AI comprehension. It utilizes static analysis to generate a hierarchical, zoomable "Cognitive Map" of any project without relying on expensive LLM tokens for structural discovery.

## Core Philosophy

- **Physical Truth:** All relationships are derived from Abstract Syntax Tree (AST) parsing using tree-sitter.
- **Hallucination Prevention:** File hashes ensure that documentation and visual maps never drift from the actual code on disk.
- **Lazy Comprehension:** Metadata is indexed instantly for search; AI-driven summaries are only generated on-demand during deep-zoom inspection.
- **Privacy Centric:** The tool operates locally, providing the Host LLM with structured metadata rather than full codebase uploads.

## Architecture

The project is divided into three primary layers:

1. **The Scanner:** A multi-language engine powered by tree-sitter that extracts symbols, imports, and hierarchies.
2. **The Indexer:** A local flat-file registry (JSON/Shelve) that maps symbols to their physical locations and relational neighbors.
3. **The Visualizer:** A zoomable user interface (ZUI) that renders code as a nested box-in-box graph, allowing users to drill down from directory to function level.

## Features

- **Multi-Language Support:** Universal AST parsing for Python, JavaScript, TypeScript, and more.
- **Semantic Navigation:** Search for logic by keyword or relationship even before AI processing.
- **ZUI Visualization:** Interactive web-based map served via a local Python server.
- **MCP Integration:** Native support for LLM orchestration, allowing agents to "query" the project map.

## Project Structure

```text
Files/
├── index.json          <-- Global relational map (Nodes, Edges, Hashes)
├── symbols.json        <-- Searchable symbol registry
└── graph/              
    └── index.html      <-- Main zoomable visualization entry point