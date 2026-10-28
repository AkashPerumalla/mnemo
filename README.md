# Mnemo

**A personal AI whose memory is a file you own.**

Submitted to the **Personal AI Track** of the Nebius x NVIDIA Global AI Hackathon.

Most assistants remember you in a place you cannot see. Mnemo inverts that: every
fact it keeps is a row in a SQLite file on your disk, shown in a pane next to the
chat, where you can read it, edit it, pin it or delete it. Memory is a product
surface, not an implementation detail.

It runs on **NVIDIA Nemotron** models served by **Nebius Token Factory**.

---

## What it does

- **Glass-box memory.** The agent decides what to remember; you keep the final say.
  Each row carries its kind, tags and provenance (`agent` or `user`), and the
  answer cites the memory ids it relied on, so you can audit any claim back to its
  source. One-click JSON export, one-click wipe.
- **Reusable skills.** A skill is a Markdown file in `skills/` that you write.
  Only each skill's name and description sit in the base prompt; the body loads
  only when the agent calls `load_skill`, so adding skills costs almost no context.
  Edit a file and the next message picks it up — no restart.
- **Tools you choose.** Live web access via Tavily, memory read/write, and skill
  loading. Tools absent from your `.env` are absent from the model's tool list
  rather than failing at call time.
- **Two-tier model routing.** Every turn starts on a fast model. The fast model
  decides for itself when a sub-problem deserves the 550B reasoning model and
  escalates by calling `think_harder`. The UI shows each escalation, so the cost
  is visible rather than hidden.

---

## How Nebius and NVIDIA are used

### NVIDIA open source models

| Role | Model ID | Why this one |
|---|---|---|
| Every turn, tool orchestration | `nvidia/Nemotron-3_5-Lightning` | 1M context and the cheapest tier — it holds the memory context plus tool results and still answers fast |
| Escalated reasoning only | `nvidia/Nemotron-3-Ultra-550b-a55b` | 550B hybrid MoE for multi-step planning and conflict resolution, invoked by the `think_harder` tool |

Both are NVIDIA open source models, and both are served through Token Factory.
`.env.example` documents the swap to `nvidia/nemotron-3-super-120b-a12b` or
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` — one env var, no code change.

### Where Token Factory accelerated the workflow

Token Factory is **OpenAI-compatible**, so the entire inference layer is the
official `openai` client with `base_url` repointed — see
[`app/agent.py`](app/agent.py):

```python
self.client = AsyncOpenAI(
    api_key=settings.nebius_api_key,
    base_url="https://api.tokenfactory.nebius.com/v1/",
)
```

Three things that cost real time on other stacks cost none here:

1. **No serving work.** Nemotron Ultra is a 550B model. Standing it up on our own
   GPUs would have consumed the whole build window; on Token Factory it is one
   model string. Two-tier routing was a config decision, not an infrastructure
   project.
2. **Tool calling worked on the first try.** The OpenAI-compatible
   `tools` / `tool_choice` contract meant no custom parser for Nemotron's output —
   the agent loop in `app/agent.py` is ~90 lines with no provider-specific shims.
3. **Switching tiers is one env var.** Comparing Lightning against Super against
   Ultra needed no redeploy, so model choice was settled by measurement.

Every runtime inference call in this project — fast turns and escalations alike —
is a call to the Token Factory inference API.

### Other services used

- **Tavily Search API** — the `web_search` tool makes a functional runtime call to
  `POST https://api.tavily.com/search` ([`app/tools.py`](app/tools.py)), used by the
  `research-note` skill to ground answers in live sources with URLs. Verified end to
  end by `scripts/verify_live.py`, which asserts the model chooses the tool, the
  search returns sources, and the cited URLs reach the answer. The tool is
  gated on `TAVILY_API_KEY`: without it the tool is never offered to the model,
  rather than failing at call time. `scripts/verify_web_search_mock.py` asserts the
  request shape against Tavily's documented contract, and the UI trace shows the
  exact URLs returned — the model sometimes normalises a URL in its prose, so the
  trace is the authoritative record of what was actually fetched.
- **Nebius Serverless Endpoints** — [`deploy/Dockerfile`](deploy/Dockerfile) is the
  deployment path, with memories on a mounted volume so they survive redeploys.

---

## Architecture

```
Browser (web/)  ──►  FastAPI (app/main.py)  ──►  Agent loop (app/agent.py)
                                                   │
                        ┌──────────────────────────┼───────────────────────────┐
                        ▼                          ▼                           ▼
            Nemotron 3.5 Lightning       Nemotron 3 Ultra            Tool dispatch
            (every turn, tools)          (via think_harder)          (app/tools.py)
                        └──────── Nebius Token Factory ──────┘           │
                                                        ┌───────────────┼────────────┐
                                                        ▼               ▼            ▼
                                                 SQLite memory    Tavily API    skills/*.md
                                                 (app/memory.py)
```

| File | Responsibility |
|---|---|
| [`app/agent.py`](app/agent.py) | Tool-calling loop, system prompt, model routing |
| [`app/memory.py`](app/memory.py) | SQLite store, inspectable token-overlap search |
| [`app/tools.py`](app/tools.py) | Tool schemas, dispatch, Tavily client |
| [`app/skills.py`](app/skills.py) | Markdown skill loader with frontmatter |
| [`app/main.py`](app/main.py) | HTTP API and static file serving |
| [`web/`](web/) | Chat UI plus the memory/skills/stack inspector |

Memory search is deliberately token-overlap scoring rather than embeddings: the
score is the fraction of query terms present, so the UI can always explain why a
row matched. For a personal corpus of a few thousand rows this is both fast enough
and honest. Swapping in embeddings means replacing one method, `MemoryStore.search`.

---

## Run it locally

Requires Python 3.11+.

```bash
git clone <your-fork-url> && cd mnemo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your keys to `.env`:

- `NEBIUS_API_KEY` — **required.** Create one at
  [tokenfactory.nebius.com](https://tokenfactory.nebius.com).
- `TAVILY_API_KEY` — optional. Without it the `web_search` tool is simply not
  offered to the model; everything else works.

Then start it:

```bash
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000>.

> If your account is pinned to a region, set `NEBIUS_BASE_URL` to the
> region-suffixed host your dashboard shows (for example
> `https://api.tokenfactory.us-central1.nebius.com/v1/`). Note that Lightning and
> Nano are served from `eu-north1` while Super and Ultra are served from
> `us-central1`.

### Verify it works

Offline, no key and no network — memory store, skill loading, tool-schema gating:

```bash
python scripts/smoke_test.py
```

The web_search chain, with a local stand-in for Tavily — a real Nemotron turn, but
no Tavily credits spent. Checks that the model chooses the tool, that our request
matches Tavily's documented contract, and that sources reach the answer. Use this
before you have a Tavily key:

```bash
python scripts/verify_web_search_mock.py
```

Live against Token Factory (spends a small number of tokens). Checks that both
Nemotron models are visible on your account, that tool calling works, that a full
agent turn writes a memory, that web_search reaches the real Tavily API, and that
escalation to Ultra fires:

```bash
python scripts/verify_live.py
```

### Three things we measured

Both came out of testing against the live API, and both changed the code:

**1. The model would claim to save without saving.** Early on, asking it to
remember something produced *"I've saved that…"* with no `remember` call and an
empty memory pane — the worst possible failure for a memory product. Adding an
explicit rule to the system prompt (*saying you saved something is not saving it*)
plus naming standing preferences as durable took the measured tool-call rate from
8/12 to **12/12, with 0/12 false claims** across three prompts run four times each.
The glass-box trace is what made the bug visible in the first place.

**2. The agent duplicated memories, and called skills as if they were tools.**
A single research turn wrote the same conclusion to memory twice and logged
`research-note -- unknown tool`: the model called the skill by its own name
instead of going through `load_skill`, so the skill (which says to save exactly
one conclusion) never loaded. Both are fixed, and deliberately fixed in different
places. The skill-name call is handled in the tool dispatcher, which now resolves
an unknown tool name against the skill list. Duplication is handled in the store,
not the prompt: `MemoryStore.add` collapses a near-identical memory into the
existing row, merging tags and keeping the longer text. A prompt can ask the model
not to repeat itself; the store should not depend on it obeying, because duplicate
rows are what turn an inspectable memory pane into noise. Collapsing is reported
back to the model and shown in the trace as *updated memory* rather than
*wrote memory*.

**3. Nemotron 3.5 Lightning is a reasoning model, so token budgets matter.** It
emits chain-of-thought into a separate `reasoning_content` field before writing
`content`. With a tight `max_tokens`, the call truncates mid-reasoning and the
partial thinking text surfaces as the answer. Our first test used
`max_tokens=12` and got `"Here's a thinking process:\n\n1. **Analyze"` instead of
`"ready"`. The orchestration call now budgets 2400 tokens.

### Deploy

```bash
docker build -f deploy/Dockerfile -t mnemo .
docker run -p 8000:8000 --env-file .env -v mnemo-data:/data mnemo
```

The same image deploys to Nebius Serverless Endpoints.

**Hugging Face Spaces** — a Space needs `Dockerfile` and a front-matter
`README.md` at its own root, so the layout is assembled rather than pushed
directly. The script reads your username from the token, creates the Space if it
does not exist, and pushes:

```bash
HF_TOKEN=hf_xxx ./scripts/deploy_space.sh
```

Then set `NEBIUS_API_KEY` and `TAVILY_API_KEY` under Settings → Variables and
secrets. `--dry-run` assembles and validates without touching the network,
checking that `app_port` matches the served port and that `short_description`
fits the Hub's 60-character limit.

> Creating a **Docker** Space on free `cpu-basic` hardware requires a PRO
> account — the Hub API says so in its own `sdk` field description. Existing
> free Spaces keep running; this applies to new ones. Without PRO, use Render
> below. The script detects the refusal and says so rather than failing opaquely.

**Render** — New → Blueprint, pick this repo, and set the two keys when
prompted. [`render.yaml`](render.yaml) is at the repo root where Render looks
for it.

Two things the blueprint handles that are easy to get wrong. Render does not
inject `PORT` for the Docker runtime and instead probes for the listening port,
so the image binds `${PORT:-8000}` and the blueprint pins `PORT` explicitly —
serving a fixed port while the platform probes another is a common way to fail a
deploy with "No open ports detected". And the free plan has an ephemeral
filesystem and cannot mount a disk at all, so it writes to `/tmp` and runs in
demo mode, where per-visitor memory is expendable by design; the blueprint has a
commented disk block for paid instances.

Free services also spin down after about 15 minutes idle and cold-start in
roughly 50 seconds.

### Verify a deployment

```bash
./scripts/verify_deployment.sh https://your-instance.example.com
```

Checks the health surface, that both API keys reached the host, that the page
and assets serve, that per-visitor isolation actually holds against two separate
cookie jars, and that a real agent turn reaches Token Factory and writes a
memory. Pass `--no-chat` to skip the turn that spends tokens.

### Public demo mode

A personal memory app has an obvious problem when you host it publicly: one
shared brain that every visitor can read, edit and wipe, paid for with your
inference credits. Setting `MNEMO_DEMO_MODE=1` fixes both.

- **Each visitor gets their own memory space**, keyed to an httponly cookie.
  Memories are owner-scoped in SQL, so another visitor's ids are not merely
  hidden — they are unreadable, unmodifiable and undeletable, and `wipe` only
  ever clears the caller's own rows.
- **A per-visitor message cap** (`MNEMO_DEMO_TURN_LIMIT`, default 25) keeps one
  visitor from spending the whole budget. The UI shows the remaining count.

Self-hosted installs are unaffected: without the flag there is one owner, no
cookie is set, and nothing is capped.

---

## Try these

1. *"I'm building a robotics side project in Rust and I keep hitting lifetime
   errors. Remember that."* — watch a row appear in the Memory pane.
2. *"What do you know about me so far?"* — the trace shows `recall` running before
   the answer, and the answer cites memory ids.
3. *"Research what changed in open-weight reasoning models this month, then file the
   conclusion."* — loads the `research-note` skill, searches via Tavily, escalates
   to Ultra if sources conflict, then writes exactly one memory.
4. Delete the memory from step 1, then ask step 2 again. It is genuinely gone.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Run one agent turn; returns reply, tool trace, models used |
| `GET` | `/api/memories` | List memories with a per-kind summary |
| `POST` | `/api/memories` | Add a memory by hand |
| `PATCH` | `/api/memories/{id}` | Edit text, kind, tags or pin |
| `DELETE` | `/api/memories/{id}` | Delete one memory |
| `GET` | `/api/memories/export` | Download every memory as JSON |
| `POST` | `/api/memories/wipe` | Delete everything |
| `GET` | `/api/skills` | List loaded skills with bodies |
| `GET` | `/api/health` | Config, models, memory and skill counts |

---

## Limitations

Honest about what this is after a short build:

- **Single user, no auth.** Mnemo is designed to run on hardware you control. Put
  it behind a reverse proxy before exposing it. Demo mode separates visitors from
  each other, which is not the same as authentication: a cookie identifies a
  browser, not a person, so it is right for a public demo and wrong for real data.
- **Demo turn counts are in memory.** A restart resets them. Acceptable for a
  demo; a real deployment would move them to the database.
- **Conversation history is client-side.** The memory store is durable; the chat
  transcript is not kept server-side and resets on reload. Durable facts survive
  precisely because the agent wrote them to memory.
- **Duplicate detection is lexical too.** Two statements of the same fact in
  entirely different words will both be stored. The threshold is deliberately
  conservative: collapsing two genuinely different memories is worse than keeping
  a near-duplicate the user can delete in one click.
- **Search is lexical.** A query phrased with entirely different words than the
  stored memory can miss. See the note on `MemoryStore.search` above.
- **No scheduler yet.** "Always-on" today means persistent state across sessions,
  not background execution. Nebius Serverless Jobs is the intended path for
  recurring skills such as `daily-brief`.

## License

[MIT](LICENSE)
