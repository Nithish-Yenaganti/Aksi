"""Optional LLM summarization for Aksi architecture context.

This module is deliberately outside the scanner/graph path. Aksi always builds
the map locally; the LLM is only used when the caller explicitly asks for
natural-language architecture summaries.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


class LLMSummaryError(RuntimeError):
    """Raised when optional LLM summarization cannot complete."""


def _trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n\n[truncated by Aksi before LLM summarization]"


def _context_payload(context: dict[str, Any]) -> dict[str, Any]:
    node = context.get("node", {})
    sources = context.get("sources")
    if not sources and context.get("source"):
        sources = [{"path": node.get("path"), "source": context.get("source", "")}]

    return {
        "node": {
            "id": node.get("id"),
            "name": node.get("name"),
            "type": node.get("type"),
            "role": node.get("role"),
            "detail": node.get("detail"),
            "files": node.get("files"),
        },
        "neighbors": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "role": item.get("role"),
            }
            for item in context.get("neighbors", [])
        ],
        "edges": context.get("edges", []),
        "file_edges": context.get("file_edges", [])[:20],
        "symbols": [
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "path": item.get("path"),
                "start_line": item.get("start_line"),
                "end_line": item.get("end_line"),
            }
            for item in context.get("symbols", [])[:80]
        ],
        "sources": [
            {"path": item.get("path"), "source": _trim(item.get("source", ""), 12_000)}
            for item in (sources or [])[:8]
        ],
    }


def _summary_prompt(context: dict[str, Any]) -> list[dict[str, str]]:
    payload = _context_payload(context)
    return [
        {
            "role": "system",
            "content": (
                "You write concise architecture explanations for a local code visualizer. "
                "Use only the provided source/context. Return strict JSON with keys: "
                "what, why, how, role. Do not invent files, services, or runtime behavior."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, indent=2),
        },
    ]


def _mock_summary(context: dict[str, Any]) -> dict[str, str]:
    node = context.get("node", {})
    files = node.get("files") or []
    file_text = ", ".join(files[:4]) if files else node.get("path") or "the selected source"
    name = node.get("name") or "Selected node"
    return {
        "what": f"{name} groups {file_text}.",
        "why": "It is included because Aksi detected it as an architecture-level unit from local source structure.",
        "how": "Aksi provided exact source context, and this mock provider produced a deterministic test summary.",
        "role": node.get("role") or "Architecture summary candidate.",
    }


def summarize_context(
    context: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
    timeout: float = 30.0,
) -> dict[str, str]:
    """Return an LLM-written summary for a get_context payload.

    Supported providers:
    - "mock": deterministic local summaries for tests and dry runs.
    - "openai": OpenAI-compatible chat completions over HTTPS.
    """

    provider_name = (provider or os.getenv("AKSI_LLM_PROVIDER") or "openai").lower()
    if provider_name == "mock":
        return _mock_summary(context)
    if provider_name != "openai":
        raise LLMSummaryError(f"Unsupported LLM provider: {provider_name}")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMSummaryError("OPENAI_API_KEY is required when summarize=True and provider=openai")

    request_payload = {
        "model": model or os.getenv("AKSI_LLM_MODEL") or DEFAULT_MODEL,
        "messages": _summary_prompt(context),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        os.getenv("AKSI_LLM_BASE_URL") or OPENAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise LLMSummaryError(f"LLM request failed: {error}") from error

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        summary = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise LLMSummaryError("LLM response did not contain valid summary JSON") from error

    return {
        "what": str(summary.get("what", "")).strip(),
        "why": str(summary.get("why", "")).strip(),
        "how": str(summary.get("how", "")).strip(),
        "role": str(summary.get("role", "")).strip(),
    }
