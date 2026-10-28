"""FastAPI app: chat endpoint, memory CRUD, skills listing, export/wipe.

Single-user by default. Set MNEMO_DEMO_MODE=1 for a public demo: each visitor
gets their own memory space keyed to a cookie, and a per-visitor turn cap keeps
one visitor from spending the whole inference budget.
"""

import json
import secrets
from typing import Any

from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .config import ROOT, settings
from .memory import DEFAULT_OWNER, KINDS, MemoryStore
from .skills import load_skills
from .tools import summarize_store

app = FastAPI(title="Mnemo", version="0.1.0")

store = MemoryStore(settings.db_path)
agent = Agent(settings, store)

WEB_DIR = ROOT / "web"
SESSION_COOKIE = "mnemo_session"

# Per-visitor turn counts for the public demo. In-memory on purpose: a restart
# clearing the counters is an acceptable failure mode for a demo, and it keeps
# the deployment free of extra moving parts.
_turns_used: dict[str, int] = {}


def resolve_owner(response: Response, session: str | None) -> str:
    """Who this request's memories belong to.

    Outside demo mode everything belongs to the single local user, which keeps
    a self-hosted install exactly as it was.
    """
    if not settings.demo_mode:
        return DEFAULT_OWNER
    if not session or not session.isalnum() or len(session) < 16:
        session = secrets.token_hex(16)
    response.set_cookie(
        SESSION_COOKIE,
        session,
        max_age=60 * 60 * 24 * 7,
        httponly=True,
        samesite="lax",
    )
    return f"demo:{session}"


def enforce_turn_budget(owner: str) -> None:
    if not settings.demo_mode:
        return
    used = _turns_used.get(owner, 0)
    if used >= settings.demo_turn_limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Demo limit of {settings.demo_turn_limit} messages reached for this "
                "browser session. Clone the repo and run it with your own Nebius key "
                "for unlimited use."
            ),
        )
    _turns_used[owner] = used + 1


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    history: list[dict[str, str]] = Field(default_factory=list)


class MemoryIn(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "note"
    tags: list[str] = Field(default_factory=list)


class MemoryPatch(BaseModel):
    text: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None


@app.get("/api/health")
def health(
    response: Response, mnemo_session: str | None = Cookie(default=None)
) -> dict[str, Any]:
    owner = resolve_owner(response, mnemo_session)
    return {
        "demo_mode": settings.demo_mode,
        "turns_left": (
            settings.demo_turn_limit - _turns_used.get(owner, 0)
            if settings.demo_mode
            else None
        ),
        "nebius_configured": settings.nebius_ready,
        "tavily_configured": settings.tavily_ready,
        "base_url": settings.nebius_base_url,
        "model_fast": settings.model_fast,
        "model_deep": settings.model_deep,
        "skills": sorted(load_skills(settings.skills_dir).keys()),
        "kinds": list(KINDS),
        "memory": summarize_store(store, owner),
        "db_path": str(settings.db_path),
    }


@app.post("/api/chat")
async def chat(
    body: ChatIn,
    response: Response,
    mnemo_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    owner = resolve_owner(response, mnemo_session)
    enforce_turn_budget(owner)
    try:
        result = await agent.run_turn(body.message, body.history, owner=owner)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token Factory call failed: {exc}") from exc
    return {
        "reply": result.reply,
        "events": result.events,
        "models_used": sorted(set(result.models_used)),
        "turns_left": (
            settings.demo_turn_limit - _turns_used.get(owner, 0)
            if settings.demo_mode
            else None
        ),
    }


@app.get("/api/memories")
def list_memories(
    response: Response,
    limit: int = 200,
    mnemo_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    owner = resolve_owner(response, mnemo_session)
    return {
        "memories": store.recent(limit=limit, owner=owner),
        "summary": summarize_store(store, owner),
    }


@app.post("/api/memories")
def create_memory(
    body: MemoryIn,
    response: Response,
    mnemo_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    owner = resolve_owner(response, mnemo_session)
    try:
        return store.add(body.text, body.kind, body.tags, source="user", owner=owner)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/memories/{mem_id}")
def patch_memory(
    mem_id: int,
    body: MemoryPatch,
    response: Response,
    mnemo_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    owner = resolve_owner(response, mnemo_session)
    updated = store.update(mem_id, owner=owner, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="memory not found")
    return updated


@app.delete("/api/memories/{mem_id}")
def delete_memory(
    mem_id: int,
    response: Response,
    mnemo_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    owner = resolve_owner(response, mnemo_session)
    if not store.delete(mem_id, owner=owner):
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": True}


@app.get("/api/memories/export")
def export_memories(
    response: Response, mnemo_session: str | None = Cookie(default=None)
) -> JSONResponse:
    owner = resolve_owner(response, mnemo_session)
    payload = {"memories": store.recent(limit=10000, owner=owner)}
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="mnemo-memories.json"'},
    )


@app.post("/api/memories/wipe")
def wipe_memories(
    response: Response, mnemo_session: str | None = Cookie(default=None)
) -> dict[str, int]:
    owner = resolve_owner(response, mnemo_session)
    return {"deleted": store.wipe(owner=owner)}


@app.get("/api/skills")
def list_skills() -> dict[str, Any]:
    skills = load_skills(settings.skills_dir)
    return {
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
                "body": s.body,
                "file": s.path.name,
            }
            for s in skills.values()
        ]
    }


class RevalidatingStatic(StaticFiles):
    """Serve assets with `no-cache` so the browser revalidates every load.

    Without this the browser happily reuses a cached app.js after an edit, which
    silently shows stale behaviour during development and demos. ETags make the
    revalidation a cheap 304.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"}
    )


if WEB_DIR.is_dir():
    app.mount("/static", RevalidatingStatic(directory=WEB_DIR), name="static")
