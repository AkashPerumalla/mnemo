"""FastAPI app: chat endpoint, memory CRUD, skills listing, export/wipe."""

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .config import ROOT, settings
from .memory import KINDS, MemoryStore
from .skills import load_skills
from .tools import summarize_store

app = FastAPI(title="Mnemo", version="0.1.0")

store = MemoryStore(settings.db_path)
agent = Agent(settings, store)

WEB_DIR = ROOT / "web"


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
def health() -> dict[str, Any]:
    return {
        "nebius_configured": settings.nebius_ready,
        "tavily_configured": settings.tavily_ready,
        "base_url": settings.nebius_base_url,
        "model_fast": settings.model_fast,
        "model_deep": settings.model_deep,
        "skills": sorted(load_skills(settings.skills_dir).keys()),
        "kinds": list(KINDS),
        "memory": summarize_store(store),
        "db_path": str(settings.db_path),
    }


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    try:
        result = await agent.run_turn(body.message, body.history)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token Factory call failed: {exc}") from exc
    return {
        "reply": result.reply,
        "events": result.events,
        "models_used": sorted(set(result.models_used)),
    }


@app.get("/api/memories")
def list_memories(limit: int = 200) -> dict[str, Any]:
    return {"memories": store.recent(limit=limit), "summary": summarize_store(store)}


@app.post("/api/memories")
def create_memory(body: MemoryIn) -> dict[str, Any]:
    try:
        return store.add(body.text, body.kind, body.tags, source="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/memories/{mem_id}")
def patch_memory(mem_id: int, body: MemoryPatch) -> dict[str, Any]:
    updated = store.update(mem_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="memory not found")
    return updated


@app.delete("/api/memories/{mem_id}")
def delete_memory(mem_id: int) -> dict[str, bool]:
    if not store.delete(mem_id):
        raise HTTPException(status_code=404, detail="memory not found")
    return {"deleted": True}


@app.get("/api/memories/export")
def export_memories() -> JSONResponse:
    payload = json.dumps({"memories": store.recent(limit=10000)}, indent=2)
    return JSONResponse(
        content=json.loads(payload),
        headers={"Content-Disposition": 'attachment; filename="mnemo-memories.json"'},
    )


@app.post("/api/memories/wipe")
def wipe_memories() -> dict[str, int]:
    return {"deleted": store.wipe()}


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
