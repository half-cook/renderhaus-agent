import os
import unittest
from unittest.mock import patch

from agent.deep_agent.routing import estimate_cost
from agent.gateway_executor import tool_needs_approval
from server.billing_rates import cost_for


class LocalRenderCostTests(unittest.TestCase):
    def test_local_render_has_no_provider_charge_and_retains_approval(self):
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local'}):
            self.assertEqual(cost_for('remotion', 'render_timeline', {}).total_cents, 0)
            self.assertEqual(estimate_cost('Remotion___render_timeline', {}).total_cents, 0)
            self.assertTrue(tool_needs_approval('Remotion___render_timeline', True))
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda'}):
            self.assertIsNone(estimate_cost('Remotion___render_timeline', {}).total_cents)
