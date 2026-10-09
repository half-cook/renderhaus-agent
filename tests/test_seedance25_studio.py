from __future__ import annotations

import unittest
import os
from unittest.mock import patch

from server.studio_options import static_field_options


class Seedance25StudioTests(unittest.TestCase):
    def test_seedance_form_lists_upgrade_and_legacy_model_with_thirty_second_limit(self):
        options = static_field_options()["seedance"]
        self.assertEqual(options["model"][0], "dreamina-seedance-2-5-260628")
        self.assertIn("seedance-1-5-pro-251215", options["model"])
        self.assertEqual(options["duration_seconds"], list(range(4, 31)))
        self.assertIn("1080p", options["resolution"])


class Seedance25StudioStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_fal_dry_run_is_visible_when_seedance_flag_is_live(self):
        from server.studio import studio_status

        with patch.dict(os.environ, {"SEEDANCE_TRANSPORT": "fal", "SEEDANCE_DRY_RUN": "false",
                                     "FAL_DRY_RUN": "true"}), patch("server.studio.agent_configured", return_value=False):
            status = await studio_status()
        self.assertTrue(status["dry_run"]["seedance"])


if __name__ == "__main__":
    unittest.main()
