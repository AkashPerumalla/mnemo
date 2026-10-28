"""Tool schemas and dispatch.

Four tools, each mapping to one thing the Personal AI track asks for:
  remember / recall -> persistent memory the user controls
  web_search        -> access to information the user chooses (Tavily)
  think_harder      -> explicit escalation from a fast model to a reasoning model
"""

from typing import Any

import httpx

from .memory import DEFAULT_OWNER, KINDS, MemoryStore

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def tool_schemas(*, tavily_enabled: bool, skill_names: list[str]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": (
                    "Save a durable fact about the user, their projects, preferences or "
                    "people. Use only for information worth recalling in a future, "
                    "unrelated conversation. Never save secrets or passwords."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The memory, as one self-contained sentence.",
                        },
                        "kind": {"type": "string", "enum": list(KINDS)},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": (
                    "Search stored memories for anything relevant before answering a "
                    "question about the user, their past decisions or their projects."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "think_harder",
                "description": (
                    "Escalate one hard sub-problem to the large reasoning model. Use for "
                    "multi-step planning, tricky analysis or anything where a fast answer "
                    "would likely be wrong. Pass the full self-contained problem statement."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "problem": {
                            "type": "string",
                            "description": "Self-contained problem, including all context needed.",
                        }
                    },
                    "required": ["problem"],
                },
            },
        },
    ]
    if tavily_enabled:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": (
                        "Search the live web for current information the stored memories "
                        "cannot answer. Returns titles, URLs and extracts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10,
                            },
                        },
                        "required": ["query"],
                    },
                },
            }
        )
    if skill_names:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "Load the full instructions for one of the user's skills before "
                        "carrying out a task it covers."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": skill_names}
                        },
                        "required": ["name"],
                    },
                },
            }
        )
    return schemas


async def tavily_search(
    api_key: str, query: str, max_results: int = 5
) -> dict[str, Any]:
    """One functional, runtime call to the Tavily Search API."""
    payload = {
        "query": query,
        "max_results": max(1, min(int(max_results or 5), 10)),
        "search_depth": "basic",
        "include_answer": True,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            TAVILY_SEARCH_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "answer": data.get("answer"),
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": (r.get("content") or "")[:700],
            }
            for r in (data.get("results") or [])
        ],
    }


def format_recall(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "No matching memories."
    return "\n".join(f"[#{m['id']} {m['kind']}] {m['text']}" for m in memories)


def summarize_store(store: MemoryStore, owner: str = DEFAULT_OWNER) -> dict[str, Any]:
    rows = store.recent(limit=1000, owner=owner)
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
    return {"total": len(rows), "by_kind": by_kind}
