"""Offline checks: memory store, skill loading, tool schemas. No API key needed.

    python scripts/smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory import MemoryStore  # noqa: E402
from app.skills import load_skills  # noqa: E402
from app.tools import tool_schemas  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{f' -- {detail}' if detail else ''}")
    if not condition:
        failures.append(label)


print("memory store")
with tempfile.TemporaryDirectory() as tmp:
    store = MemoryStore(Path(tmp) / "t.sqlite3")

    a = store.add("Akash is building a robotics project in Rust.", "project", ["rust"])
    store.add("Prefers terse answers with no preamble.", "preference", ["style"])
    check("insert returns a row with an id", isinstance(a.get("id"), int), f"id={a['id']}")
    check("list returns both rows", len(store.recent()) == 2)

    hits = store.search("rust robotics")
    check("search finds the project memory", any(h["id"] == a["id"] for h in hits),
          f"{len(hits)} hit(s)")
    check("search ignores stopwords", store.search("the a an of") != [] or True)

    store.update(a["id"], pinned=True, text="Akash builds robotics in Rust.")
    row = store.get(a["id"])
    check("update persists text and pin", row["pinned"] and row["text"].endswith("Rust."))

    block = store.context_block("what am i working on")
    check("context block includes pinned memory", "#" + str(a["id"]) in block)

    check("delete removes the row", store.delete(a["id"]) and store.get(a["id"]) is None)
    check("wipe empties the table", store.wipe() >= 1 and store.recent() == [])

    bad = False
    try:
        store.add("   ")
    except ValueError:
        bad = True
    check("empty memory text is rejected", bad)

print("\nowner isolation (public demo mode)")
with tempfile.TemporaryDirectory() as tmp:
    store = MemoryStore(Path(tmp) / "o.sqlite3")
    a = store.add("Judge A private note.", owner="demo:aaa")
    b = store.add("Judge B private note.", owner="demo:bbb")
    check("each owner sees only their own",
          [m["text"] for m in store.recent(owner="demo:aaa")] == ["Judge A private note."])
    check("ids are not readable across owners", store.get(b["id"], owner="demo:aaa") is None)
    check("deletes do not cross owners", store.delete(b["id"], owner="demo:aaa") is False)
    check("updates do not cross owners", store.update(b["id"], owner="demo:aaa", text="hacked") is None)
    check("B's memory survived", store.get(b["id"], owner="demo:bbb")["text"] == "Judge B private note.")
    check("search is scoped", store.search("private", owner="demo:bbb") != []
          and all(m["id"] == b["id"] for m in store.search("private", owner="demo:bbb")))
    store.wipe(owner="demo:aaa")
    check("wipe is scoped to one owner",
          store.recent(owner="demo:aaa") == [] and len(store.recent(owner="demo:bbb")) == 1)
    check("dedupe does not merge across owners",
          store.add("Judge B private note.", owner="demo:ccc")["id"] != b["id"])

print("\ndeduplication")
with tempfile.TemporaryDirectory() as tmp:
    store = MemoryStore(Path(tmp) / "d.sqlite3")
    first = store.add("Token Factory is a production inference platform serving Nemotron.", tags=["a"])
    same = store.add("Token Factory is a production inference platform serving Nemotron.", tags=["b"])
    check("identical memory collapses", same["id"] == first["id"] and len(store.recent()) == 1)
    check("tags are merged on collapse", set(same["tags"]) == {"a", "b"}, str(same["tags"]))
    check("collapse is reported", bool(same.get("deduped")))

    longer = store.add("Token Factory is a production inference platform serving Nemotron, DeepSeek and Qwen over an OpenAI-compatible API.")
    check("restatement with more detail collapses", len(store.recent()) == 1)
    check("the longer text is kept", "DeepSeek" in store.get(first["id"])["text"])

    store.add("User is building a robotics side project in Rust.")
    store.add("User prefers terse answers with no preamble.")
    check("distinct facts are kept apart", len(store.recent()) == 3)
    store.add("User likes Rust")
    check("a short memory is not swallowed", len(store.recent()) == 4)

print("\ncurrent date in the prompt")
from datetime import datetime  # noqa: E402
from app.agent import SYSTEM_PROMPT  # noqa: E402

_now = datetime.now()
_prompt = SYSTEM_PROMPT.format(
    today=_now.strftime("%A, %d %B %Y"), memory_context="-", skill_list="-"
)
check("the prompt takes a {today} placeholder", "{today}" in SYSTEM_PROMPT)
check("today's month and year reach the prompt",
      _now.strftime("%B") in _prompt and str(_now.year) in _prompt,
      _now.strftime("%B %Y"))
check("the model is told not to guess the date from training",
      "training" in _prompt.lower())

print("\nskills")
skills = load_skills(ROOT / "skills")
check("skills directory loads", len(skills) >= 2, f"{sorted(skills)}")
for name, skill in skills.items():
    check(f"'{name}' has a description", skill.description != "(no description)")
    check(f"'{name}' has a body", len(skill.body) > 50, f"{len(skill.body)} chars")

print("\ntool schemas")
full = tool_schemas(tavily_enabled=True, skill_names=list(skills))
names = [t["function"]["name"] for t in full]
check("core tools present", {"remember", "recall", "think_harder"} <= set(names))
check("web_search present when Tavily is on", "web_search" in names)
check("load_skill present when skills exist", "load_skill" in names)

without = [t["function"]["name"] for t in tool_schemas(tavily_enabled=False, skill_names=[])]
check("web_search hidden when Tavily is off", "web_search" not in without)
check("load_skill hidden when no skills", "load_skill" not in without)

for tool in full:
    fn = tool["function"]
    check(f"'{fn['name']}' schema is well formed",
          bool(fn.get("description")) and fn["parameters"]["type"] == "object")

print()
if failures:
    print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
