"""Guard against the recurring deploy.yml / Dockerfile.agentcore merge conflict.

Those files used to carry literal provider/tool/skill/routing counts that every
feature branch bumped. Counts are now derived by agent.inventory at build time.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.inventory import inventory

ROOT = Path(__file__).resolve().parents[1]


class InventoryLiteralGuardTests(unittest.TestCase):
    def test_dockerfile_has_no_inline_count_asserts(self) -> None:
        text = (ROOT / "Dockerfile.agentcore").read_text()
        self.assertIn("python -m agent.inventory", text)
        self.assertNotRegex(text, r"assert\s+(len|sum)\(")
        self.assertNotRegex(text, r"==\s*\d{2,}")

    def test_deploy_workflow_step_names_carry_no_counts(self) -> None:
        text = (ROOT / ".github/workflows/deploy.yml").read_text()
        self.assertNotRegex(text, r"\d+\s+(providers|tools|skills|routing rows|active routes|catalog styles)")

    def test_inventory_is_derived_and_consistent(self) -> None:
        counts = inventory()
        self.assertEqual(
            set(counts),
            {"providers", "tools", "skills", "catalog_styles", "shot_recipes", "routing_rows", "active_routes"},
        )
        self.assertTrue(all(isinstance(v, int) and v > 0 for v in counts.values()))
        skills = len(list((ROOT / "agent/deep_agent/skills").glob("*/SKILL.md")))
        self.assertEqual(counts["skills"], skills)

    def test_adding_a_skill_needs_no_edit_to_either_file(self) -> None:
        # A branch that adds a skill folder only changes the derived number.
        import tempfile
        from unittest.mock import patch

        from agent.deep_agent import runner

        with tempfile.TemporaryDirectory() as directory:
            skills_root = Path(directory)
            for p in runner.SKILLS_ROOT.iterdir():
                if p.is_dir():
                    (skills_root / p.name).symlink_to(p, target_is_directory=True)
            (skills_root / "brand-new-skill").mkdir()
            (skills_root / "brand-new-skill" / "SKILL.md").write_text("---\nname: x\n---\n")
            baseline = inventory()["skills"]
            with patch.object(runner, "SKILLS_ROOT", skills_root):
                self.assertEqual(inventory()["skills"], baseline + 1)

    def test_skill_folder_without_skill_md_fails(self) -> None:
        import tempfile
        from unittest.mock import patch

        from agent.deep_agent import runner

        with tempfile.TemporaryDirectory() as directory:
            skills_root = Path(directory)
            for p in runner.SKILLS_ROOT.iterdir():
                if p.is_dir():
                    (skills_root / p.name).symlink_to(p, target_is_directory=True)
            (skills_root / "half-copied").mkdir()
            with patch.object(runner, "SKILLS_ROOT", skills_root):
                with self.assertRaisesRegex(AssertionError, "half-copied"):
                    inventory()


if __name__ == "__main__":
    unittest.main()
