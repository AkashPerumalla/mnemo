"""Prove the web_search chain without spending Tavily credits.

Runs a real agent turn against Nemotron on Token Factory, but points the Tavily
client at a local stand-in server. Verifies that the model chooses the tool, that
the request we send matches Tavily's documented contract, that we parse the
response, and that sources reach the answer.

Needs NEBIUS_API_KEY. Does NOT need TAVILY_API_KEY -- use this to validate the
integration before you have a key, then use verify_live.py once you do.

    python scripts/verify_web_search_mock.py
"""

import asyncio
import dataclasses
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.tools as tools_mod  # noqa: E402
from app.agent import Agent  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import MemoryStore  # noqa: E402

PORT = 8787
captured: dict = {}
failures: list[str] = []

FAKE_RESPONSE = {
    "answer": "Nebius Token Factory is an inference platform for open models.",
    "results": [
        {
            "title": "Token Factory docs",
            "url": "https://docs.tokenfactory.nebius.com/",
            "content": "Token Factory serves open-source models over an OpenAI-compatible API.",
        },
        {
            "title": "Nemotron on Nebius",
            "url": "https://nebius.com/services/token-factory/nemotron",
            "content": "NVIDIA Nemotron models are served on Nebius Token Factory.",
        },
    ],
}


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not ok:
        failures.append(label)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        captured["body"] = json.loads(self.rfile.read(length) or b"{}")
        captured["auth"] = self.headers.get("Authorization", "")
        out = json.dumps(FAKE_RESPONSE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


async def main() -> int:
    if not settings.nebius_ready:
        print("NEBIUS_API_KEY is not set -- this script still needs a real model call.")
        return 2

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tools_mod.TAVILY_SEARCH_URL = f"http://127.0.0.1:{PORT}/search"

    # A Settings with a fake Tavily key, so the tool is offered to the model.
    stub = dataclasses.replace(settings, tavily_api_key="tvly-TESTKEY")

    print("agent turn with a stand-in Tavily\n")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            agent = Agent(stub, MemoryStore(Path(tmp) / "t.sqlite3"))
            result = await agent.run_turn(
                "Search the web for what Nebius Token Factory is and cite the URLs."
            )

        tools_used = [e["tool"] for e in result.events]
        check("model chose web_search", "web_search" in tools_used, f"tools: {tools_used}")

        body = captured.get("body", {})
        check("request reached the Tavily endpoint", bool(body))
        check("auth header is a bearer token",
              captured.get("auth", "").startswith("Bearer tvly-"))
        check("request carries a query", bool(body.get("query")), repr(body.get("query")))
        check("max_results within Tavily's 1-20 range",
              1 <= int(body.get("max_results", 0)) <= 20, str(body.get("max_results")))
        check("search_depth is valid",
              body.get("search_depth") in {"basic", "advanced", "fast", "ultra-fast"},
              str(body.get("search_depth")))

        sources = [u for e in result.events for u in (e.get("sources") or [])]
        check("response parsed into sources", len(sources) == 2, f"{sources}")
        check("reply cites a url", "http" in result.reply.lower())
    except Exception as exc:
        check("agent turn completed", False, str(exc)[:300])
    finally:
        server.shutdown()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("web_search integration verified (stand-in Tavily, real Nemotron)")
    print("Add TAVILY_API_KEY to .env and run verify_live.py to confirm the real API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
