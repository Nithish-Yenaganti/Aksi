# Contributing to Aksi

Search existing issues and pull requests first. Aksi keeps repository facts local and lets the MCP host supply grounded summaries; preserve that boundary when proposing changes.

## Setup and checks

Use Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m py_compile scanner.py graph.py mcp_server.py aksi.py
.venv/bin/python -m pytest
```

Follow [AGENTS.md](AGENTS.md) for the MCP completion contract. Add regression coverage for changed behavior; a viewer file existing is not sufficient evidence that the workflow completed.

## Bug reports

Include your commit, Python version, operating system, MCP client, a minimal sample repository, tool-call sequence, expected behavior, and actual status or error. Remove credentials and private code. For stale-context reports, describe the file change that should have invalidated a summary or model.

Generated `Files/` output and `.mcp/` settings are local artifacts and should not be committed.

## Pull requests

Use a title describing the changed behavior. Explain the problem, the smallest fix, relevant tests, and any checks you could not run. Update setup or workflow documentation when user-visible behavior changes. If a PR is superseded or withdrawn, link the replacement or explain the outcome.
