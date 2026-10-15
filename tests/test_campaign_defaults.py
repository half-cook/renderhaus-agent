import os
import unittest
from unittest.mock import patch


class CampaignDefaults(unittest.TestCase):
    def test_server_default_seedance_model_is_2_5(self):
        from providers.seedance.contracts import MODEL_25
        from server.config import DEFAULT_ENV

        self.assertEqual(DEFAULT_ENV["SEEDANCE_MODEL"], MODEL_25)

    def test_config_endpoint_never_exposes_model_names(self):
        import asyncio
        import json

        from providers.seedance.contracts import MODEL_25
        from server import app

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SEEDANCE_MODEL", None)
            payload = asyncio.run(app.config())
        for key in ("video_model", "image_model", "music_model"):
            self.assertNotIn(key, payload)
        self.assertNotIn(MODEL_25, json.dumps(payload))

    def test_gpt_image_estimate_is_finite_for_approval_cards(self):
        from agent.deep_agent.routing import estimate_cost

        for tool in ("generate_image", "edit_image"):
            quote = estimate_cost(f"OpenAI___{tool}", {"prompt": "x"}, list_price=True)
            self.assertEqual(quote.total_cents, 26)
            self.assertNotIn("unknown", quote.description.lower())


if __name__ == "__main__":
    unittest.main()
