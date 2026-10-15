"""Build-time inventory checks that derive their numbers from the tree.

Deploy and the AgentCore image used to assert literal counts (providers, tools,
skills, routing rows, catalog styles). Every feature branch that added a skill
or a routing row edited those same two lines in .github/workflows/deploy.yml and
Dockerfile.agentcore, so every pair of branches conflicted there. These checks
keep the guarantee (the image holds every packaged file and they all load)
without a number that changes per feature.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pinned(package: str) -> str | None:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(rf'"{re.escape(package)}(?:\[[^\]]*\])?==([^"]+)"', text)
    return match.group(1) if match else None


def inventory(root: Path = ROOT) -> dict[str, int]:
    from agent.deep_agent import runner
    from agent.deep_agent.runner import SKILLS_ROOT
    from providers.catalog import PROVIDERS
    from providers.registry import load_committed_schemas

    pin = _pinned("deepagents")
    assert pin, "deepagents must stay pinned with == in pyproject.toml"
    assert importlib.metadata.version("deepagents") == pin, "installed deepagents differs from the pin"

    skill_dirs = [p for p in SKILLS_ROOT.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))]
    missing = [p.name for p in skill_dirs if not (p / "SKILL.md").is_file()]
    assert not missing, f"skill folders without SKILL.md: {missing}"
    skills = len(skill_dirs)
    assert skills > 0

    assert PROVIDERS, "no providers registered"
    tools = sum(len(load_committed_schemas(spec)) for spec in PROVIDERS)
    assert tools > 0, "no committed Gateway tool schemas"

    catalog = json.loads((SKILLS_ROOT / "art-style-motion/references/catalog/index.json").read_text())
    styles = len(catalog["styles"])
    assert styles > 0 and catalog["counts"]["catalog_styles"] == styles, "style catalog counts disagree"

    recipes_root = root / "providers" / "shot_recipes"
    index = json.loads((recipes_root / "index.json").read_text())
    cards = len(list((recipes_root / "cards").glob("*/*.md")))
    assert cards > 0 and cards == len(index["cards"]), "shot recipe index and card files disagree"

    cases = json.loads((root / "tests/fixtures/skill_routing.json").read_text())
    ids = [c["test_id"] for c in cases if c.get("test_id")]
    assert len(ids) == len(set(ids)), "Routing fixture IDs must be unique."
    active = sum(not c["skip_reason"] for c in cases)
    assert active > 0
    counts = {
        "providers": len(PROVIDERS),
        "tools": tools,
        "skills": skills,
        "catalog_styles": styles,
        "shot_recipes": cards,
        "routing_rows": len(cases),
        "active_routes": active,
    }
    harness_tools = getattr(runner, "HARNESS_TOOL_NAMES", None)
    if harness_tools is not None:  # present once agent-harness-v2 is merged
        assert harness_tools, "no harness tools registered"
        counts["harness_tools"] = len(harness_tools)
    return counts


def main() -> None:
    counts = inventory()
    print("ok inventory " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
