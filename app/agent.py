"""The agent loop: a tool-calling conversation served by Nemotron on Nebius Token Factory.

Model routing is the point of this file. Every turn starts on the fast model
(Nemotron 3.5 Lightning). The fast model decides for itself when a sub-problem
needs the 550B reasoning model (Nemotron 3 Ultra) and escalates by calling the
think_harder tool. Both calls go to the same Token Factory endpoint.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI

from .config import Settings
from .memory import DEFAULT_OWNER, MemoryStore
from .skills import Skill, load_skills
from .tools import format_recall, tavily_search, tool_schemas

MAX_STEPS = 6

# Low, not zero: tool-call reliability drops noticeably as this rises, and the
# orchestration model's job is routing, not prose.
ORCHESTRATION_TEMPERATURE = 0.1
# Lightning is a reasoning model -- it spends tokens on reasoning_content before
# emitting content, so a tight budget truncates mid-thought.
REASONING_TEMPERATURE = 0.4

SYSTEM_PROMPT = """You are Mnemo, a personal AI assistant that runs on infrastructure \
the user controls. You are concise, concrete and never sycophantic.

Today is {today}. Use it for anything time-relative -- "today", "this month",
"next week", whether a deadline has passed -- and in search queries when the
user wants recent information. Never fall back on a date from your training
data: it is years out and will quietly produce stale answers.

How you work:
- You have a persistent memory the user can read, edit and delete. Call `recall` \
before answering anything about the user, their projects or their past decisions. \
Call `remember` when you learn something durable and worth knowing in a future \
conversation -- not for small talk, and never for secrets or credentials.
- Anything the user tells you to keep in mind, remember, or apply going forward \
is durable by definition -- including preferences about how you should behave, \
deadlines, and standing instructions. Acknowledging it in prose is not enough: \
call `remember`. When in doubt, save it; the user can delete it in one click.
- HARD RULE: never tell the user you lack web access, live data or current \
information once a tool in this turn has returned results. You have those \
results; use them. If they are thin, say what you found and what is still \
missing. Do not fall back on what you remember and do not call your own \
knowledge frozen or out of date.
- HARD RULE: saying you saved something is not saving it. Never claim you have \
remembered, saved, stored or noted anything unless you actually called the \
`remember` tool in this same turn. If the user asks you to remember something, \
call `remember` first, then answer. The user can see which tools you called, so a \
false claim is always visible.
- You run on a fast model. When a sub-problem needs real reasoning (multi-step \
planning, careful analysis, tradeoffs), call `think_harder` and use what it returns.
- The user's skills are procedures they wrote. If one applies, call `load_skill` \
with its name first, then follow it. A skill is not itself a tool -- never try to \
call one directly by its name.
- Call `remember` at most once per distinct fact in a turn. If a tool result says \
a fact was already saved or updated, do not save it again.
- Cite memory ids like [#12] when you rely on a stored memory, and cite URLs when \
you rely on a web search.

Stored memories relevant to this turn:
{memory_context}

Skills available (load before using):
{skill_list}"""


@dataclass
class TurnResult:
    reply: str
    events: list[dict[str, Any]] = field(default_factory=list)
    models_used: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, settings: Settings, store: MemoryStore):
        self.settings = settings
        self.store = store
        self.client = AsyncOpenAI(
            api_key=settings.nebius_api_key or "missing-key",
            base_url=settings.nebius_base_url,
        )

    async def _complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None,
        temperature: float = ORCHESTRATION_TEMPERATURE,
    ):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2400,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return await self.client.chat.completions.create(**kwargs)

    @staticmethod
    def _evidence(transcript, limit: int = 4) -> str:
        """Tool results gathered so far in this turn, for the reasoning model.

        Without this the reasoning model is blind: it cannot see the web results
        the orchestrator just fetched, so it reasons from training alone and
        reports that it cannot know anything recent -- which the orchestrator
        then repeats to the user, contradicting its own search.
        """
        results = [
            str(m.get("content") or "") for m in transcript if m.get("role") == "tool"
        ]
        if not results:
            return ""
        joined = "\n\n".join(r[:1500] for r in results[-limit:])
        return (
            "\n\nEvidence already gathered in this conversation. Treat it as "
            "current and authoritative, and reason from it rather than from what "
            "you remember:\n\n" + joined
        )

    async def _think_harder(self, problem: str, transcript=None) -> str:
        """Escalate to the large reasoning model. No tools -- it reasons and returns."""
        resp = await self._complete(
            self.settings.model_deep,
            [
                {
                    "role": "system",
                    "content": (
                        f"Today is {datetime.now().strftime('%A, %d %B %Y')}. "
                        "You are a careful reasoning engine consulted mid-conversation "
                        "by another agent that has live tools. Work through the problem "
                        "step by step, then state a clear conclusion. Be rigorous and "
                        "flag any assumption you had to make. Never say you lack web "
                        "access or current information: the agent consulting you has "
                        "already gathered what is needed; reason over it."
                    ),
                },
                {
                    "role": "user",
                    "content": problem + self._evidence(transcript or []),
                },
            ],
            tools=None,
            temperature=REASONING_TEMPERATURE,
        )
        return (resp.choices[0].message.content or "").strip()

    async def _run_tool(
        self,
        name: str,
        args: dict[str, Any],
        skills: dict[str, Skill],
        owner: str,
        transcript=None,
    ) -> tuple[str, dict[str, Any]]:
        """Returns (content for the model, event for the UI trace)."""
        if name == "remember":
            mem = self.store.add(
                text=args.get("text", ""),
                kind=args.get("kind", "note"),
                tags=args.get("tags") or [],
                source="agent",
                owner=owner,
            )
            deduped = bool(mem.get("deduped"))
            verb = "Updated existing" if deduped else "Saved as"
            return (
                f"{verb} memory #{mem['id']}. Do not save this fact again.",
                {
                    "tool": "remember",
                    "detail": mem["text"],
                    "memory_id": mem["id"],
                    "deduped": deduped,
                },
            )

        if name == "recall":
            hits = self.store.search(
                args.get("query", ""),
                limit=int(args.get("limit") or 8),
                owner=owner,
            )
            return (
                format_recall(hits),
                {
                    "tool": "recall",
                    "detail": f"{len(hits)} match(es) for \"{args.get('query', '')}\"",
                    "memory_ids": [h["id"] for h in hits],
                },
            )

        if name == "think_harder":
            answer = await self._think_harder(args.get("problem", ""), transcript)
            return (
                answer or "(the reasoning model returned nothing)",
                {
                    "tool": "think_harder",
                    "detail": f"escalated to {self.settings.model_deep}",
                    "model": self.settings.model_deep,
                },
            )

        if name == "web_search":
            if not self.settings.tavily_ready:
                return "Web search is not configured.", {
                    "tool": "web_search",
                    "detail": "TAVILY_API_KEY not set",
                }
            try:
                data = await tavily_search(
                    self.settings.tavily_api_key,
                    args.get("query", ""),
                    int(args.get("max_results") or 5),
                )
            except Exception as exc:  # network/4xx/5xx -- report, do not crash the turn
                return f"Web search failed: {exc}", {
                    "tool": "web_search",
                    "detail": f"error: {exc}",
                }
            lines = []
            if data.get("answer"):
                lines.append(f"Tavily summary: {data['answer']}")
            for r in data["results"]:
                lines.append(f"- {r['title']} ({r['url']})\n  {r['content']}")
            return "\n".join(lines) or "No results.", {
                "tool": "web_search",
                "detail": f"{len(data['results'])} result(s) for \"{args.get('query', '')}\"",
                "sources": [r["url"] for r in data["results"]],
            }

        if name == "load_skill":
            skill = skills.get(args.get("name", ""))
            if not skill:
                return f"No skill named {args.get('name')!r}.", {
                    "tool": "load_skill",
                    "detail": f"not found: {args.get('name')}",
                }
            return f"# Skill: {skill.name}\n\n{skill.body}", {
                "tool": "load_skill",
                "detail": skill.name,
            }

        # Nemotron sometimes calls a skill by its own name rather than going
        # through load_skill. Treat that as the load it obviously meant.
        slug = name.lower().replace("_", "-")
        for skill_name, skill in skills.items():
            if skill_name.lower() == slug:
                return f"# Skill: {skill.name}\n\n{skill.body}", {
                    "tool": "load_skill",
                    "detail": skill.name,
                }

        return f"Unknown tool {name!r}.", {"tool": name, "detail": "unknown tool"}

    async def run_turn(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        owner: str = DEFAULT_OWNER,
    ) -> TurnResult:
        if not self.settings.nebius_ready:
            raise RuntimeError(
                "NEBIUS_API_KEY is not set. Copy .env.example to .env and add your key "
                "from https://tokenfactory.nebius.com"
            )

        skills = load_skills(self.settings.skills_dir)
        skill_list = (
            "\n".join(s.summary() for s in skills.values()) or "(no skills installed)"
        )
        system = SYSTEM_PROMPT.format(
            today=datetime.now().strftime("%A, %d %B %Y"),
            memory_context=self.store.context_block(user_message, owner=owner),
            skill_list=skill_list,
        )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for turn in (history or [])[-10:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_message})

        tools = tool_schemas(
            tavily_enabled=self.settings.tavily_ready,
            skill_names=list(skills.keys()),
        )

        result = TurnResult(reply="", models_used=[self.settings.model_fast])

        for _ in range(MAX_STEPS):
            resp = await self._complete(self.settings.model_fast, messages, tools)
            msg = resp.choices[0].message
            calls = msg.tool_calls or []

            if not calls:
                result.reply = (msg.content or "").strip()
                return result

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.function.name,
                                "arguments": c.function.arguments,
                            },
                        }
                        for c in calls
                    ],
                }
            )

            for call in calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                content, event = await self._run_tool(
                    call.function.name, args, skills, owner, messages
                )
                result.events.append(event)
                if event.get("model"):
                    result.models_used.append(event["model"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )

        # Ran out of steps: ask for a final answer with no tools available.
        resp = await self._complete(self.settings.model_fast, messages, tools=None)
        result.reply = (resp.choices[0].message.content or "").strip()
        return result
