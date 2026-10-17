from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


from server.studio_state import StudioRepository, UsageCharge


class BetaFixture:
    def setUp(self):
        from server.beta_credits import BetaSettings

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.repo = StudioRepository(self.path / "state.sqlite3", self.path / "media")
        self.settings = BetaSettings(enabled=True, global_cap_cents=100_000,
                                     identity_salt="test-only-identity-salt")

    def configure(self, **changes):
        self.settings = replace(self.settings, **changes)

    def grant(self, account="one"):
        from server.beta_invites import BetaInvites
        invites = BetaInvites(self.repo, self.settings)
        return invites.redeem(account, invites.mint()[0], email=f"{account}@example.com")

    def rows(self, sql, args=()):
        with self.repo._connect() as connection:
            return connection.execute(sql, args).fetchall()

    def assert_denied(self, action, message="Not eligible for free beta credit."):
        from server.beta_credits import BetaError
        with self.assertRaises(BetaError) as caught:
            action()
        self.assertEqual(str(caught.exception), message)


class BetaCreditsTests(BetaFixture, unittest.TestCase):


    def test_spending_and_refunds_preserve_free_and_paid_value(self):
        self.grant()
        self.repo.adjust_balance("one", 500, "purchase")
        charge = self.repo.charge_usage("one", 1200, "generation")
        self.assertEqual(charge.beta_cents, 1000)
        self.assertEqual(charge.wallet_cents, 1200)
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 0)
        self.assertEqual(self.repo.get_beta_credit("one")["spent_cents"], 1000)
        self.assertEqual(self.repo.get_balance("one"), 300)
        self.repo.refund_usage("one", charge, "refund")
        self.repo.refund_usage("one", charge, "refund retried")
        self.assertEqual(self.repo.get_balance("one"), 1500)
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 1000)
        self.assertEqual(sum(row["delta"] for row in self.repo.list_ledger("one", limit=100)), 1500)

    def test_spending_never_exceeds_grant_and_still_works_after_closure(self):
        self.configure(global_cap_cents=1000)
        self.grant()
        self.configure(enabled=False)
        charge = self.repo.charge_usage("one", 1000, "generation")
        self.assertEqual(charge.beta_cents, 1000)
        with self.assertRaisesRegex(ValueError, "free beta credit is used up"):
            self.repo.charge_usage("one", 1, "generation")
        self.assertEqual(self.repo.get_balance("one"), 0)
        self.repo.refund_usage("one", charge, "failed")
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 1000)
        self.configure(enabled=True)
        self.assertEqual(self.repo.get_beta_credit("one")["granted_cents"], 1000)

    def test_direct_wallet_debit_cannot_leave_spendable_beta_above_balance(self):
        self.grant()
        self.repo.adjust_balance("one", -900, "manual debit")
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 100)
        self.assertEqual(self.repo.charge_usage("one", 100, "generation").beta_cents, 100)


    def test_forged_beta_refund_is_refused(self):
        self.grant()
        with self.assertRaises(ValueError):
            self.repo.refund_usage("one", UsageCharge(0, 2000, "2026-10-09", beta_cents=2000), "forged")
        self.assertEqual(self.repo.get_balance("one"), 1000)

    def test_negative_cost_refused(self):
        with self.assertRaises(ValueError):
            self.repo.charge_usage("one", -10, "negative")
        self.assertEqual(self.repo.get_balance("one"), 0)

    def test_refund_cannot_discard_provenance_or_change_charge_date(self):
        self.grant()
        charge = self.repo.charge_usage("one", 250, "generation")
        for forged in (replace(charge, charge_id=None, beta_cents=0),
                       replace(charge, beta_cents=0),
                       replace(charge, charge_date="2099-01-01")):
            with self.assertRaises(ValueError):
                self.repo.refund_usage("one", forged, "forged")
        self.assertEqual(self.repo.get_balance("one"), 750)

    def test_beta_refund_recovers_durably_after_failure_without_duplicate_value(self):
        self.grant()
        charge = self.repo.charge_usage("one", 600, "generation")
        with patch.object(self.repo, "_apply_refund", side_effect=RuntimeError("temporary")):
            self.repo.refund_usage("one", charge, "failed")
            self.repo.refund_usage("one", charge, "retry")
        other = StudioRepository(self.repo.database_path, self.repo.media_root)
        self.assertEqual(other.get_balance("one"), 1000)
        self.assertEqual(other.get_beta_credit("one")["remaining_cents"], 1000)

    def test_concurrent_spending_and_refund_replay_is_bounded(self):
        self.grant()
        def charge(_):
            try:
                return self.repo.charge_usage("one", 100, "generation")
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=30) as pool:
            charges = [result for result in pool.map(charge, range(30)) if result]
        self.assertEqual(len(charges), 10)
        self.assertEqual(sum(charge.beta_cents for charge in charges), 1000)
        with ThreadPoolExecutor(max_workers=30) as pool:
            list(pool.map(lambda _: self.repo.refund_usage("one", charges[0], "replay"), range(30)))
        self.assertEqual(self.repo.get_balance("one"), 100)
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 100)
        self.assertEqual(sum(row["delta"] for row in self.repo.list_ledger("one", limit=100)), 100)


    def test_concurrent_legacy_schema_migration(self):
        self.repo.init()
        with self.repo._connect() as connection:
            for column in ("beta_cents", "refunded_at", "charge_date"):
                connection.execute(f"ALTER TABLE usage_events DROP COLUMN {column}")
            for column in ("beta_cents", "charge_id"):
                connection.execute(f"ALTER TABLE pending_refunds DROP COLUMN {column}")
        connect = sqlite3.connect
        class SlowSchemaConnection:
            def __init__(self, *args, **kwargs):
                self.connection = connect(*args, **kwargs)
            def __getattr__(self, name):
                return getattr(self.connection, name)
            def execute(self, sql, *args):
                cursor = self.connection.execute(sql, *args)
                if sql == "PRAGMA table_info(usage_events)":
                    rows = list(cursor)
                    time.sleep(.03)
                    return rows
                return cursor
        def initialize(_):
            StudioRepository(self.repo.database_path, self.repo.media_root).init()
        with patch("server.studio_state.sqlite3.connect", SlowSchemaConnection), ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(initialize, range(4)))
        self.assertEqual(self.repo.get_balance("one"), 0)


class BetaBillingIntegrationTests(BetaFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.grant()
        self.enterContext(patch.dict("os.environ", {"STRIPE_SECRET_KEY": "", "BETA_CREDITS_ENABLED": "true"}))
        self.repo.create_project("user:one", "one", "Beta test", project_id="beta-project")

    async def test_studio_invocation_debits_and_rejects_when_free_credit_exhausted_without_stripe(self):
        from fastapi import HTTPException
        from server.studio import InvokeBody, invoke_tool, quote_tool
        body = InvokeBody(provider="seedream", tool="text_to_image", arguments={"prompt": "robot"}, project_id="beta-project")
        from server.billing_rates import GenerationCost
        with patch("server.studio.repository", self.repo), patch("server.studio.cost_for", return_value=GenerationCost(1000, 0)), \
                patch("server.studio.dispatch", return_value={"status": "queued", "job_id": "offline"}):
            body.approval_token = (await quote_tool(body, SimpleNamespace(payload={"sub": "one"})))["approval_token"]
            await invoke_tool(body, SimpleNamespace(payload={"sub": "one"}))
            self.assertEqual(self.repo.get_balance("one"), 0)
            with self.assertRaises(HTTPException) as caught:
                await invoke_tool(body, SimpleNamespace(payload={"sub": "one"}))
            self.assertEqual(caught.exception.status_code, 402)
            self.assertIn("free beta credit is used up", caught.exception.detail)

    async def test_gateway_debits_and_refunds_with_real_wallet_and_mock_transport(self):
        from agent.gateway_client import GatewayClient
        from agent.studio_agent_next import GatewayMCPServer
        gateway = GatewayMCPServer({"url": "https://unused.invalid"}, name="gateway", user_id="one")
        with patch("agent.studio_agent_next.repository", self.repo), \
                patch("agent.studio_agent_next.cost_for", return_value=SimpleNamespace(total_cents=250)), \
                patch.object(GatewayClient, "call_tool", new_callable=AsyncMock) as call:
            call.return_value = {"status": "dry_run"}
            await gateway.call_tool("Seedream___text_to_image", {"prompt": "robot"})
            self.assertEqual(self.repo.get_balance("one"), 750)
            call.return_value = {"status": "failed", "error": "mock failure"}
            with self.assertRaises(RuntimeError):
                await gateway.call_tool("Seedream___text_to_image", {"prompt": "robot"})
            self.assertEqual(self.repo.get_balance("one"), 750)
            self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 750)
            for status in ("blocked", "not_run"):
                call.return_value = {"status": status, "reason": "No work performed."}
                with self.assertRaises(RuntimeError):
                    await gateway.call_tool("Seedream___text_to_image", {"prompt": "robot"})
                self.assertEqual(self.repo.get_balance("one"), 750)
            with patch.dict("os.environ", {"BETA_CREDITS_ENABLED": "false"}):
                call.return_value = {"status": "dry_run"}
                await gateway.call_tool("Seedream___text_to_image", {"prompt": "robot"})
                self.assertEqual(self.repo.get_balance("one"), 500)

    async def test_local_agent_dispatch_uses_beta_wallet(self):
        from mcp import Tool
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        gateway = SimpleNamespace(list_tools=AsyncMock(return_value=[Tool(name="Remotion___render_ad_variants", inputSchema={"type": "object"})]))
        studio = _context_from_request(StudioAgentRequest(prompt="ad variants", user_id="one", job_id="beta-run"))
        executor = GatewayExecutor(studio, [gateway])
        with patch("server.studio_state.repository", self.repo), \
                patch("server.billing_rates.cost_for", return_value=SimpleNamespace(total_cents=300, provider_cents=300, fee_cents=0)), \
                patch("providers.registry.dispatch", return_value={"status": "dry_run"}):
            result = await executor.execute({"tool_name": "Remotion___render_ad_variants", "arguments": {
                "stage": "render_first", "job_id": "beta-run", "brief": {"campaign": "demo"},
                "rows": [{"variant_key": "demo", "sku": "demo", "price_text": "$1", "cta_text": "Try",
                          "logo_asset": "logo.png", "legal_text": "Terms apply", "locale": "en-CA", "aspect": "1:1"}],
                "master_asset": "master.mp4", "plan_hash": "a" * 64}, "call_id": "local"}, approved=True)
            self.assertEqual(result["status"], "dry_run", result)
        self.assertEqual(self.repo.get_balance("one"), 700)

    async def test_account_response_includes_recovered_beta_refund(self):
        from server.studio import studio_account
        charge = self.repo.charge_usage("one", 600, "generation")
        with patch.object(self.repo, "_apply_refund", side_effect=RuntimeError("temporary")), self.assertLogs("server.studio_state", level="ERROR"):
            self.repo.refund_usage("one", charge, "failed")
        balance = self.repo.get_balance
        def delayed_balance(account):
            time.sleep(.03)
            return balance(account)
        with patch("server.studio.repository", self.repo), patch.object(self.repo, "get_balance", side_effect=delayed_balance):
            response = await studio_account(SimpleNamespace(payload={"sub": "one"}))
        self.assertEqual(response["balance_cents"], 1000)
        self.assertEqual(response["beta_credit"]["remaining_cents"], 1000)

    async def test_local_render_failure_refunds_and_insufficient_credit_prevents_dispatch(self):
        from mcp import Tool
        from providers.registry import dispatch as real_dispatch
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        gateway = SimpleNamespace(list_tools=AsyncMock(return_value=[Tool(name="Remotion___render_ad_variants", inputSchema={"type": "object"})]))
        arguments = {"stage": "render_first", "job_id": "beta-run", "brief": {"campaign": "demo"},
            "rows": [{"variant_key": "demo", "sku": "demo", "price_text": "$1", "cta_text": "Try",
                      "logo_asset": "logo.png", "legal_text": "Terms apply", "locale": "en-CA", "aspect": "1:1"}],
            "master_asset": "master.mp4", "plan_hash": "a" * 64}
        partial_failure = {"status": "failed", "error": "mock failure", "rendered": [{"variant_key": "demo"}],
                           "failed": [{"variant_key": "second"}], "manifest_path": "manifest.json", "plan_hash": "a" * 64}
        for cost, failure in ((300, partial_failure), (300, RuntimeError("mock transport failure")),
                              (300, {"status": "blocked", "reason": "No work performed."}),
                              (300, {"status": "not_run", "reason": "No work performed."}), (1001, None)):
            with self.subTest(cost=cost, failure=failure):
                studio = _context_from_request(StudioAgentRequest(prompt="ad variants", user_id="one", job_id="beta-run"))
                executor = GatewayExecutor(studio, [gateway])
                with patch.dict("os.environ", {"REMOTION_RENDER_BACKEND": "lambda"}), \
                        patch("server.studio_state.repository", self.repo), \
                        patch("server.billing_rates.cost_for", return_value=SimpleNamespace(total_cents=cost, provider_cents=cost, fee_cents=0)), \
                        patch("providers.registry.dispatch") as dispatch:
                    if isinstance(failure, Exception):
                        dispatch.side_effect = failure
                    elif isinstance(failure, dict) and failure["status"] == "blocked":
                        dispatch.side_effect = real_dispatch
                    else:
                        dispatch.return_value = failure
                    result = await executor.execute({"tool_name": "Remotion___render_ad_variants",
                        "arguments": arguments, "call_id": "local"}, approved=True)
                    self.assertIn(result["status"], {"failed", "blocked", "not_run"}, result)
                    self.assertEqual(dispatch.call_count, 0 if cost > 1000 else 1)
                    if failure is partial_failure:
                        for key in ("rendered", "failed", "manifest_path", "plan_hash"):
                            self.assertEqual(result.get(key), failure[key])
                self.assertEqual(self.repo.get_balance("one"), 1000)
                self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 1000)
                self.assertEqual(sum(row["delta"] for row in self.repo.list_ledger("one")), 1000)

    async def test_studio_no_work_results_refund_the_grant(self):
        from server.studio import InvokeBody, invoke_tool, quote_tool
        from server.billing_rates import GenerationCost
        body = InvokeBody(provider="seedream", tool="text_to_image", arguments={"prompt": "robot"}, project_id="beta-project")
        for status in ("failed", "error", "blocked", "not_run"):
            with self.subTest(status=status), patch("server.studio.repository", self.repo), \
                    patch("server.studio.cost_for", return_value=GenerationCost(300, 0)), \
                    patch("server.studio.dispatch", return_value={"status": status, "reason": "No work performed."}):
                body.approval_token = (await quote_tool(body, SimpleNamespace(payload={"sub": "one"})))["approval_token"]
                result = await invoke_tool(body, SimpleNamespace(payload={"sub": "one"}))
                self.assertEqual(result["result"]["status"], status)
                self.assertEqual(result["assets"], [])
                self.assertEqual(self.repo.get_balance("one"), 1000)
                self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 1000)

    def test_actual_remotion_dry_run_quote_is_zero_without_changing_live_quote(self):
        from server.billing_rates import cost_for
        arguments = {"stage": "render_first", "rows": [{"sku": "demo", "locale": "en-CA"}]}
        with patch.dict("os.environ", {"REMOTION_DRY_RUN": "true", "REMOTION_RENDER_BACKEND": "local"}):
            self.assertEqual(cost_for("remotion", "render_ad_variants", arguments).total_cents, 0)
        with patch.dict("os.environ", {"REMOTION_DRY_RUN": "false", "REMOTION_RENDER_BACKEND": "local", "REMOTION_LICENSE_RENDER_USD": "0.01"}):
            self.assertEqual(cost_for("remotion", "render_ad_variants", arguments).total_cents, 1)


if __name__ == "__main__":
    unittest.main()


def test_precheck_start_explains_credit_held_by_waiting_runs():
    from server import run_billing

    class Repo:
        def conversation_has_hold(self, user_id, conversation_id):
            return False

        def available_credit(self, user_id):
            return 50

        def get_balance(self, user_id):
            return 900

    import server.run_budget as rb
    orig = (run_billing.billing_applies, rb.orchestration_billing_enabled, rb.orchestration_estimate_cents, rb.default_cap_cents)
    run_billing.billing_applies = lambda repo, user: True
    rb.orchestration_billing_enabled = lambda: True
    rb.orchestration_estimate_cents = lambda: 75
    rb.default_cap_cents = lambda estimate: 300
    try:
        payload = run_billing.precheck_start(Repo(), "u1", "c1")
    finally:
        run_billing.billing_applies, rb.orchestration_billing_enabled, rb.orchestration_estimate_cents, rb.default_cap_cents = orig
    assert payload["reason"] == "credit_held"
    assert payload["held_cents"] == 850
    assert "waiting for your approval" in payload["message"]
