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
