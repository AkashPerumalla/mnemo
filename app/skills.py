"""Reusable skills: plain Markdown files the user writes and the agent loads on demand.

A skill is a procedure, not a prompt hack. Only the name + description of each
skill goes into the system prompt; the body is loaded only when the agent calls
load_skill, which keeps the base context small no matter how many skills exist.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    triggers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"- {self.name}: {self.description}"


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Minimal `key: value` frontmatter between --- fences. No YAML dependency."""
    if not raw.startswith("---"):
        return {}, raw
    lines = raw.splitlines()
    meta: dict[str, str] = {}
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[idx + 1 :]).strip()
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, raw


def load_skills(skills_dir: Path) -> dict[str, Skill]:
    """Read every *.md in skills_dir. Called per request so edits hot-reload."""
    skills: dict[str, Skill] = {}
    if not skills_dir.is_dir():
        return skills
    for path in sorted(skills_dir.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(raw)
        name = meta.get("name") or path.stem
        triggers = [t.strip() for t in meta.get("triggers", "").split(",") if t.strip()]
        skills[name] = Skill(
            name=name,
            description=meta.get("description", "(no description)"),
            body=body,
            path=path,
            triggers=triggers,
        )
    return skills
