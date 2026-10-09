from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import server.studio as studio
from test_sync_wiring import ARGS


class SyncStudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_invoke_cannot_bypass_agent_cost_approval(self):
        body = studio.InvokeBody(provider="sync", tool="lipsync_video", arguments=ARGS, project_id="untitled")
        with patch.object(studio.repository, "require_project"), patch.object(studio, "dispatch") as dispatch, \
                patch.object(studio, "cost_for") as quote, patch.object(studio.repository, "charge_usage") as charge:
            with self.assertRaises(HTTPException) as denied:
                await studio.invoke_tool(body, None)
            self.assertEqual(denied.exception.status_code, 409)
            self.assertIn("approval", denied.exception.detail.lower())
            dispatch.assert_not_called()
            quote.assert_not_called()
            charge.assert_not_called()

    async def test_studio_reports_shared_fal_dry_run_guard(self):
        with patch.dict(os.environ, {"SYNC_TRANSPORT": "fal", "SYNC_DRY_RUN": "false", "FAL_DRY_RUN": "true"}), \
                patch.object(studio, "agent_configured", return_value=False):
            status = await studio.studio_status()
        self.assertTrue(status["dry_run"]["sync"])
