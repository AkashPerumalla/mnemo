"""Live end-to-end check against Nebius Token Factory. Needs NEBIUS_API_KEY in .env.

    python scripts/verify_live.py

Spends a small number of tokens. Never prints key material.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from app.agent import Agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import MemoryStore  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not ok:
        failures.append(label)
    return ok


async def main() -> int:
    if not settings.nebius_ready:
        print("NEBIUS_API_KEY is empty in .env.\n")
        print("  1. Get a key at https://tokenfactory.nebius.com")
        print("  2. Put it in .env as NEBIUS_API_KEY=...")
        print("  3. Re-run this script.")
        return 2

    print(f"base url   {settings.nebius_base_url}")
    print(f"fast model {settings.model_fast}")
    print(f"deep model {settings.model_deep}")
    print(f"tavily     {'configured' if settings.tavily_ready else 'not configured'}\n")

    client = AsyncOpenAI(
        api_key=settings.nebius_api_key, base_url=settings.nebius_base_url
    )

    # 1. Which models does this account actually see?
    print("model catalog")
    available: set[str] = set()
    try:
        listing = await client.models.list()
        available = {m.id for m in listing.data}
        check("model list reachable", True, f"{len(available)} model(s)")
        for label, model in (("fast", settings.model_fast), ("deep", settings.model_deep)):
            hit = model in available
            near = [m for m in available if "emotron" in m]
            check(
                f"{label} model available: {model}",
                hit,
                "" if hit else f"not in catalog; Nemotron ids seen: {sorted(near) or 'none'}",
            )
    except Exception as exc:
        check("model list reachable", False, str(exc)[:200])

    # 2. Smallest possible real inference call.
    print("\ninference")
    try:
        resp = await client.chat.completions.create(
            model=settings.model_fast,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=400,
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        check("fast model chat completion", bool(text), repr(text[:60]))
        usage = getattr(resp, "usage", None)
        if usage:
            print(f"        tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out")
    except Exception as exc:
        check("fast model chat completion", False, str(exc)[:200])

    try:
        resp = await client.chat.completions.create(
            model=settings.model_deep,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=400,
            temperature=0,
        )
        check("deep model chat completion", bool((resp.choices[0].message.content or "").strip()))
    except Exception as exc:
        check("deep model chat completion", False, str(exc)[:200])

    # 3. Tool calling is the thing most likely to differ between providers.
    print("\ntool calling")
    try:
        resp = await client.chat.completions.create(
            model=settings.model_fast,
            messages=[{"role": "user", "content": "Remember that my favourite language is Rust."}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "remember",
                        "description": "Save a durable fact about the user.",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                }
            ],
            tool_choice="auto",
            max_tokens=200,
        )
        calls = resp.choices[0].message.tool_calls or []
        check("fast model emits tool calls", bool(calls),
              calls[0].function.name if calls else "no tool_calls returned")
    except Exception as exc:
        check("fast model emits tool calls", False, str(exc)[:200])

    # 4. Tavily, if configured.
    if settings.tavily_ready:
        print("\ntavily")
        try:
            async with httpx.AsyncClient(timeout=30.0) as hc:
                r = await hc.post(
                    "https://api.tavily.com/search",
                    json={"query": "Nebius Token Factory", "max_results": 2},
                    headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
                )
            check("tavily search responds", r.status_code == 200, f"HTTP {r.status_code}")
            if r.status_code == 200:
                check("tavily returns results", bool(r.json().get("results")))
        except Exception as exc:
            check("tavily search responds", False, str(exc)[:200])

    # 5. A full agent turn against a throwaway store.
    print("\nagent turn (writes to a temp store, not your real memory file)")
    with tempfile.TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "verify.sqlite3")
        agent = Agent(settings, store)
        try:
            result = await agent.run_turn(
                "Remember that I'm building a robotics side project in Rust. "
                "Then tell me in one sentence what you just saved."
            )
            check("turn returned a reply", bool(result.reply), result.reply[:90])
            tools_used = [e["tool"] for e in result.events]
            print(f"        tools: {tools_used or 'none'}")
            check("agent wrote a memory", store.recent() != [],
                  f"{len(store.recent())} row(s)")
            for row in store.recent():
                print(f"        #{row['id']} [{row['kind']}] {row['text'][:70]}")
        except Exception as exc:
            check("turn returned a reply", False, str(exc)[:300])

        # 6. Escalation to the reasoning model.
        try:
            result = await agent.run_turn(
                "Think carefully: I have two deploy options for a 550B model, one with "
                "40% lower latency but 3x cost, the other cheap but queued. Weigh the "
                "tradeoff for an interactive personal assistant and commit to one."
            )
            escalated = any(e["tool"] == "think_harder" for e in result.events)
            check("agent escalated to the reasoning model", escalated,
                  f"models: {sorted(set(result.models_used))}")
            if not escalated:
                print("        (not fatal -- the fast model judged it answerable alone)")
                failures.remove("agent escalated to the reasoning model")
        except Exception as exc:
            check("escalation turn completed", False, str(exc)[:300])

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("live end-to-end verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
