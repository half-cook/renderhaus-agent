from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server.studio import (
    InvokeBody,
    _hydrate_tool_event_assets,
    _normalize_canvas_document,
    _register_payload_assets,
    invoke_tool,
)
from server.studio_state import StudioRepository


class LumaAssetPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.repository = StudioRepository(root / "studio.sqlite3", root / "media")
        self.repository.create_project("workspace", "user", "Luma", project_id="project")
        self.source = root / "clip.mp4"
        self.source.write_bytes(b"offline media fixture")

    def _register(self, **kwargs):
        return self.repository.register_file(
            workspace_id="workspace", project_id="project", user_id="user", path=self.source, **kwargs,
        )

    def test_non_training_flag_survives_repository_reopen_and_canvas(self):
        reference = self._register(training_eligible=False)
        reopened = StudioRepository(self.repository.database_path, self.repository.media_root)
        read = reopened.get_version("workspace", reference.version_id)
        self.assertIs(read.training_eligible, False)
        self.assertIs(read.public()["training_eligible"], False)
        self.assertIs(read.canvas()["trainingEligible"], False)
        self.assertEqual(reopened.version_path("workspace", reference.version_id).read_bytes(), self.source.read_bytes())

    def test_derived_media_inherits_non_training_restriction(self):
        source = self._register(training_eligible=False)
        derived = self._register(source_version_ids=[source.version_id], training_eligible=True)
        self.assertIs(derived.training_eligible, False)
        self.assertIs(self.repository.get_version("workspace", derived.version_id).training_eligible, False)
        self.assertIsNone(self._register().training_eligible)

    def test_luma_payload_is_ingested_with_persistent_restriction(self):
        with patch("server.studio.repository", self.repository), patch("server.studio._resolved_media_file", return_value=self.source):
            assets = _register_payload_assets(
                payload={"result": {"provider": "luma", "status": "succeeded", "training_eligible": False, "output_path": str(self.source)}},
                workspace_id="workspace", project_id="project", user_id="user",
            )
        self.assertEqual(len(assets), 1)
        self.assertIs(assets[0]["training_eligible"], False)
        self.assertIs(self.repository.get_version("workspace", assets[0]["version_id"]).training_eligible, False)

    def test_hydration_preserves_policy_when_reconstructing_output_stub(self):
        event = SimpleNamespace(
            id="tool", name="Luma___get_video_task", status="completed", assets=[],
            result={"provider": "luma", "status": "succeeded", "training_eligible": False, "output_path": str(self.source)},
        )
        with patch("server.studio.repository", self.repository), patch("server.studio._resolved_media_file", return_value=self.source):
            _hydrate_tool_event_assets([event], workspace_id="workspace", project_id="project", user_id="user", execution_id=None)
        self.assertEqual(len(event.assets), 1)
        self.assertIs(event.assets[0]["training_eligible"], False)

    def test_canvas_cannot_override_server_owned_restriction(self):
        reference = self._register(training_eligible=False)
        forged = {**reference.canvas(), "trainingEligible": True}
        with patch("server.studio.repository", self.repository):
            document = _normalize_canvas_document(
                {"nodes": [{"data": {"output": forged, "variants": []}}]},
                workspace_id="workspace", project_id="project", user_id="user",
            )
        self.assertIs(document["nodes"][0]["data"]["output"]["trainingEligible"], False)

    async def test_invoke_infers_restricted_source_from_asset_handles(self):
        source = self._register(training_eligible=False)
        body = InvokeBody(
            provider="seedream", tool="image_to_image", project_id="project",
            arguments={"prompt": "Edit", "image_path_or_url": f"renderhaus-asset://{source.version_id}"},
        )
        with (
            patch("server.studio.repository", self.repository),
            patch("server.studio.current_workspace_id", return_value="workspace"),
            patch("server.studio.current_user_id", return_value="user"),
            patch("server.studio.stripe_enabled", return_value=False),
            patch("server.studio.publish_provider_input_url", return_value="https://example.test/source.mp4"),
            patch("server.studio.dispatch", return_value={"status": "succeeded", "output_path": str(self.source)}),
            patch("server.studio._resolved_media_file", return_value=self.source),
        ):
            result = await invoke_tool(body, SimpleNamespace())
        self.assertIs(result["assets"][0]["training_eligible"], False)

    def test_legacy_database_migration_keeps_eligibility_unknown(self):
        reference = self._register()
        with sqlite3.connect(self.repository.database_path) as connection:
            connection.execute("ALTER TABLE asset_versions DROP COLUMN training_eligible")
        migrated = StudioRepository(self.repository.database_path, self.repository.media_root)
        self.assertIsNone(migrated.get_version("workspace", reference.version_id).training_eligible)
        migrated_again = StudioRepository(self.repository.database_path, self.repository.media_root)
        self.assertIsNone(migrated_again.get_version("workspace", reference.version_id).training_eligible)


if __name__ == "__main__":
    unittest.main()
