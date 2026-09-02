"""Skill loading (spec §40 Skill System, Phase 12): a `SKILL.md` is
versioned, evaluable procedural knowledge -- not a blob injected into every
context, but a discrete unit a retriever (retriever.py) can select or skip.
Mirrors Claude Code / Claude Agent SDK's own SKILL.md convention (frontmatter
+ body), which is exactly the prior art `docs/PHASES.md` cites for this
phase.

Deliberately no YAML dependency: frontmatter here is flat key: value pairs
(name/description/version), not nested structure, so a full YAML parser
would be an unneeded dependency for what a few lines of string splitting
handles correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_DELIMITER = "---"


@dataclass
class Skill:
    name: str
    description: str
    version: int
    body: str
    source_path: str


def parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_DELIMITER):
        raise ValueError(f"{path}: missing frontmatter (file must start with '---')")
    parts = text.split(_FRONTMATTER_DELIMITER, 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: malformed frontmatter (need an opening and closing '---')")
    frontmatter_text, body = parts[1], parts[2].strip()

    fields: dict[str, str] = {}
    for line in frontmatter_text.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    name = fields.get("name")
    if not name:
        raise ValueError(f"{path}: frontmatter missing required 'name' field")
    description = fields.get("description", "")
    try:
        version = int(fields.get("version", "1"))
    except ValueError:
        raise ValueError(f"{path}: 'version' must be an integer") from None

    return Skill(name=name, description=description, version=version, body=body, source_path=str(path))


def discover_skills(skills_dir: str | Path) -> list[Skill]:
    """Every `<skills_dir>/*/SKILL.md`, sorted by name for determinism. A
    missing directory (e.g. a non-editable install with no bundled skills/)
    returns an empty list rather than raising -- the Skill System degrading
    to "no skills available" is honest; a stack trace on every job isn't.
    A malformed individual skill file is skipped rather than failing the
    whole discovery pass -- every skill here is authored in this repo, so
    the risk a skip silently hides is "a typo in a file we wrote", not
    "untrusted third-party content slipping through".
    """
    root = Path(skills_dir)
    if not root.exists():
        return []
    skills = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        try:
            skills.append(parse_skill_file(skill_md))
        except ValueError:
            continue
    return skills
