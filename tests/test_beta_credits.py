from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.studio_state import StudioRepository, UsageCharge


class BetaFixture:
    def setUp(self):
        from server.beta_credits import BetaCredits, BetaSettings

        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.repo = StudioRepository(self.path / "state.sqlite3", self.path / "media")
        self.settings = BetaSettings(enabled=True, global_cap_cents=100_000, wave_size=100,
                                     identity_salt="test-only-identity-salt")
        self.beta = BetaCredits(self.repo, self.settings)

    def configure(self, **changes):
        from server.beta_credits import BetaCredits
        self.settings = replace(self.settings, **changes)
        self.beta = BetaCredits(self.repo, self.settings)

    def verify(self, account="one", email="one@example.com", phone="+14165550101"):
        email_challenge = self.beta.start_email(account, email)
        self.beta.confirm_email(account, email_challenge["challenge_id"], "beta-email-ok")
        phone_challenge = self.beta.start_phone(account, phone)
        self.beta.confirm_phone(account, phone_challenge["challenge_id"], "424242")

    def rows(self, sql, args=()):
        with self.repo._connect() as connection:
            return connection.execute(sql, args).fetchall()

    def assert_denied(self, action, message="Not eligible for free beta credit."):
        from server.beta_credits import BetaError
        with self.assertRaises(BetaError) as caught:
            action()
        self.assertEqual(str(caught.exception), message)


class BetaCreditsTests(BetaFixture, unittest.TestCase):
    def test_grant_default_and_configured_amount(self):
        self.verify()
        result = self.beta.claim("one")
        self.assertEqual(result["balance_cents"], 1000)
        self.assertEqual(result["grant"]["amount_cents"], 1000)
        self.assertEqual(self.repo.list_ledger("one")[0]["reason"], "beta_grant")
        self.configure(grant_cents=250)
        self.verify("two", "two@example.com", "+14165550102")
        self.assertEqual(self.beta.claim("two")["balance_cents"], 250)

    def test_same_account_retry_is_idempotent_even_when_full(self):
        self.configure(global_cap_cents=1000, wave_size=1)
        self.verify()
        self.beta.claim("one")
        self.assertEqual(self.beta.claim("one")["balance_cents"], 1000)
        self.assertEqual(len(self.rows("SELECT * FROM beta_grants")), 1)
        self.assertEqual(len(self.repo.list_ledger("one")), 1)

    def test_disabled_never_claims_even_on_retry(self):
        self.verify()
        self.beta.claim("one")
        self.configure(enabled=False)
        self.assert_denied(lambda: self.beta.claim("one"), "Free beta credits are disabled.")
        self.assertEqual(self.repo.get_balance("one"), 1000)

    def test_each_identity_uniquely_blocks_other_accounts(self):
        self.verify()
        self.beta.claim("one")
        for account, email, phone in [("two", "one@example.com", "+14165550102"),
                                      ("three", "three@example.com", "+14165550101")]:
            self.verify(account, email, phone)
            self.assert_denied(lambda: self.beta.claim(account))
            self.assertEqual(self.repo.get_balance(account), 0)
        self.assertEqual(len(self.rows("SELECT * FROM beta_audit WHERE outcome = 'denied'")), 2)

    def test_email_only_and_phone_only_and_neither_are_denied(self):
        for kind in ("email", "phone", "neither"):
            if kind == "email":
                challenge = self.beta.start_email(kind, "only@example.com")
                self.beta.confirm_email(kind, challenge["challenge_id"], "beta-email-ok")
            if kind == "phone":
                challenge = self.beta.start_phone(kind, "+14165550101")
                self.beta.confirm_phone(kind, challenge["challenge_id"], "424242")
            self.assert_denied(lambda: self.beta.claim(kind))

    def test_email_normalization_collisions(self):
        from server.beta_credits import normalize_email
        self.assertEqual(normalize_email("  First.Last+tag@GoogleMail.com  "), "firstlast@gmail.com")
        self.assertEqual(normalize_email("A.B+tag@Example.com"), "a.b@example.com")
        self.verify("one", "First.Last+tag@gmail.com")
        self.beta.claim("one")
        self.verify("two", "firstlast@gmail.com", "+14165550102")
        self.assert_denied(lambda: self.beta.claim("two"))

    def test_phone_normalization_and_invalid_identifiers(self):
        from server.beta_credits import normalize_phone
        self.assertEqual(normalize_phone("+1 (416) 555-0101"), "+14165550101")
        for phone in ("4165550101", "+01234567", "+1x4165550101", "+123", "+1234567890123456"):
            with self.assertRaises(ValueError):
                normalize_phone(phone)
        for email in ("", "a@@example.com", "@example.com", "a@localhost", "a b@example.com"):
            with self.assertRaises(ValueError):
                self.beta.start_email("one", email)

    def test_cap_boundaries_and_exact_messages(self):
        for cap in (0, 999, 1000):
            with self.subTest(cap=cap):
                self.configure(global_cap_cents=cap)
                status = self.beta.get_beta_status()
                if cap < 1000:
                    self.assertTrue(status["programme_full"])
                    self.assertEqual(status["spots_left"], 0)
                    self.assertEqual(status["message"], "The free beta credit is fully allocated.")
                    self.assert_denied(lambda: self.beta.claim("one"), status["message"])
                else:
                    self.verify()
                    self.beta.claim("one")
                    self.assertEqual(self.beta.get_beta_status()["message"], "The free beta credit is fully allocated.")

    def test_wave_boundary_waitlist_and_next_wave(self):
        self.configure(wave_size=1)
        self.assertEqual(self.beta.get_beta_status()["message"], "1 spots left in this wave")
        self.verify()
        self.beta.claim("one")
        status = self.beta.get_beta_status()
        self.assertFalse(status["programme_full"])
        self.assertEqual(status["spots_left"], 0)
        self.assertEqual(status["message"], "This wave is full. Join the waitlist for the next one.")
        self.assert_denied(lambda: self.beta.claim("two"), status["message"])
        self.beta.waitlist("two", "two+wait@example.com")
        self.beta.waitlist("two", "two@example.com")
        self.assertEqual(len(self.rows("SELECT * FROM beta_waitlist")), 1)
        self.assertEqual(self.beta.next_wave()["wave"], 2)
        self.assertEqual(self.beta.get_beta_status()["spots_left"], 1)

    def test_zero_wave_and_daily_limit_close_admission(self):
        self.configure(wave_size=0)
        self.assertEqual(self.beta.get_beta_status()["spots_left"], 0)
        self.assert_denied(lambda: self.beta.claim("one"), "This wave is full. Join the waitlist for the next one.")
        self.configure(wave_size=100, daily_grant_limit=1)
        self.verify()
        self.beta.claim("one")
        self.verify("two", "two@example.com", "+14165550102")
        self.assert_denied(lambda: self.beta.claim("two"), "Today's beta grant limit has been reached. Try again tomorrow.")
        with patch("server.beta_credits.time.time", return_value=2_000_000_000):
            self.assertEqual(self.beta.claim("two")["balance_cents"], 1000)

    def test_concurrent_claims_respect_wave_and_cap_across_connections(self):
        from server.beta_credits import BetaCredits, BetaError
        self.configure(wave_size=3, global_cap_cents=3000)
        for index in range(30):
            self.verify(f"racer{index}", f"racer{index}@example.com", f"+1416555{index:04d}")

        def race(index):
            repo = StudioRepository(self.repo.database_path, self.repo.media_root)
            beta = BetaCredits(repo, self.settings)
            try:
                return beta.claim(f"racer{index}")["balance_cents"]
            except BetaError:
                return 0

        with ThreadPoolExecutor(max_workers=30) as pool:
            results = list(pool.map(race, range(30)))
        self.assertEqual(results.count(1000), 3)
        self.assertEqual(sum(results), 3000)
        self.assertEqual(self.beta.get_beta_status()["spots_left"], 0)
        self.assertEqual(sum(row[0] for row in self.rows("SELECT amount_cents FROM beta_grants")), 3000)

    def test_concurrent_last_cap_grant(self):
        from server.beta_credits import BetaError
        self.configure(wave_size=30, global_cap_cents=1000)
        for index in range(30):
            self.verify(f"racer{index}", f"racer{index}@example.com", f"+1416555{index:04d}")
        def race(index):
            try:
                self.beta.claim(f"racer{index}")
                return True
            except BetaError:
                return False
        with ThreadPoolExecutor(max_workers=30) as pool:
            self.assertEqual(sum(pool.map(race, range(30))), 1)

    def test_transaction_rolls_back_grant_and_identity_on_wallet_failure(self):
        self.verify()
        with patch.object(self.repo, "_apply_balance_delta", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                self.beta.claim("one")
        self.assertEqual(len(self.rows("SELECT * FROM beta_grants")), 0)
        self.assertEqual(self.repo.get_balance("one"), 0)
        self.assertEqual(self.repo.list_ledger("one"), [])
        self.assertEqual(self.beta.claim("one")["balance_cents"], 1000)

    def test_verification_fails_closed_without_registered_live_provider(self):
        self.configure(verification_dry_run=False)
        self.assert_denied(lambda: self.beta.start_email("one", "one@example.com"), "Beta verification is unavailable.")
        self.assert_denied(lambda: self.beta.start_phone("one", "+14165550101"), "Beta verification is unavailable.")
        self.assertEqual(len(self.rows("SELECT * FROM beta_verifications")), 0)

    def test_invalid_settings_and_missing_live_salt_refuse(self):
        from server.beta_credits import BetaSettings
        for key in ("BETA_GRANT_CENTS", "BETA_GLOBAL_CAP_CENTS", "BETA_WAVE_SIZE", "BETA_WAVE_INDEX", "BETA_DAILY_GRANT_LIMIT"):
            for value in ("", "-1", "1.5", "unlimited", "9223372036854775808"):
                with self.subTest(key=key, value=value), patch.dict("os.environ", {key: value}, clear=True):
                    with self.assertRaisesRegex(ValueError, key):
                        BetaSettings.from_env()
        for key in ("BETA_CREDITS_ENABLED", "BETA_VERIFICATION_DRY_RUN"):
            with patch.dict("os.environ", {key: "maybe"}, clear=True):
                with self.assertRaisesRegex(ValueError, key):
                    BetaSettings.from_env()
        with patch.dict("os.environ", {"BETA_CREDITS_ENABLED": "true", "BETA_VERIFICATION_DRY_RUN": "false"}, clear=True):
            with self.assertRaisesRegex(ValueError, "BETA_IDENTITY_SALT"):
                BetaSettings.from_env()
        with patch.dict("os.environ", {}, clear=True):
            defaults = BetaSettings.from_env()
            self.assertFalse(defaults.enabled)
            self.assertEqual((defaults.grant_cents, defaults.wave_size, defaults.global_cap_cents, defaults.wave_index), (1000, 50, 50000, 1))

    def test_stale_mock_verification_cannot_claim_after_switching_to_live(self):
        self.verify()
        self.configure(verification_dry_run=False)
        self.assert_denied(lambda: self.beta.claim("one"), "Beta verification is unavailable.")

    def test_challenges_are_bound_to_account_expire_and_reset_on_restart(self):
        challenge = self.beta.start_email("one", "one@example.com")
        self.assert_denied(lambda: self.beta.confirm_email("two", challenge["challenge_id"], "beta-email-ok"), "Verification could not be confirmed.")
        with patch("server.beta_credits.time.time", return_value=2_000_000_000):
            self.assert_denied(lambda: self.beta.confirm_email("one", challenge["challenge_id"], "beta-email-ok"), "Verification could not be confirmed.")
        self.verify()
        self.beta.start_email("one", "changed@example.com")
        self.assert_denied(lambda: self.beta.claim("one"))

    def test_wrong_codes_are_not_verification(self):
        challenge = self.beta.start_email("one", "one@example.com")
        self.assert_denied(lambda: self.beta.confirm_email("one", challenge["challenge_id"], "anything"), "Verification could not be confirmed.")
        self.assert_denied(lambda: self.beta.claim("one"))

    def test_rate_limits_identifiers_and_accounts_persist(self):
        from server.beta_credits import BetaCredits
        for _ in range(5):
            self.beta.start_email("one", "rate@example.com")
        beta = BetaCredits(self.repo, self.settings)
        self.assert_denied(lambda: beta.start_email("two", "rate+tag@example.com"), "Too many verification attempts. Try again later.")
        for index in range(10):
            beta.start_email("account-rate", f"unique{index}@example.com")
        self.assert_denied(lambda: beta.start_phone("account-rate", "+14165550101"), "Too many verification attempts. Try again later.")

    def test_hashes_only_in_verification_waitlist_and_audit(self):
        self.verify()
        self.beta.claim("one")
        with self.repo._connect() as connection:
            dump = "\n".join(connection.iterdump())
        self.assertNotIn("one@example.com", dump)
        self.assertNotIn("14165550101", dump)
        self.assertNotIn("test-only-identity-salt", dump)
        row = self.rows("SELECT email_hash, phone_hash FROM beta_grants")[0]
        self.assertEqual(len(row["email_hash"]), 64)
        self.assertEqual(len(row["phone_hash"]), 64)
        with self.assertRaises(sqlite3.IntegrityError), self.repo._connect() as connection:
            connection.execute("UPDATE beta_grants SET phone_hash = NULL")

    def test_spending_and_refunds_preserve_free_and_paid_value(self):
        self.verify()
        self.beta.claim("one")
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
        self.verify()
        self.beta.claim("one")
        self.configure(enabled=False)
        charge = self.repo.charge_usage("one", 1000, "generation")
        self.assertEqual(charge.beta_cents, 1000)
        with self.assertRaisesRegex(ValueError, "free beta credit is used up"):
            self.repo.charge_usage("one", 1, "generation")
        self.assertEqual(self.repo.get_balance("one"), 0)
        self.repo.refund_usage("one", charge, "failed")
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 1000)
        self.configure(enabled=True)
        self.assertTrue(self.beta.get_beta_status()["programme_full"])

    def test_direct_wallet_debit_cannot_leave_spendable_beta_above_balance(self):
        self.verify()
        self.beta.claim("one")
        self.repo.adjust_balance("one", -900, "manual debit")
        self.assertEqual(self.repo.get_beta_credit("one")["remaining_cents"], 100)
        self.assertEqual(self.repo.charge_usage("one", 100, "generation").beta_cents, 100)

    def test_subscription_allowance_then_beta_then_paid(self):
        self.verify()
        self.beta.claim("one")
        self.repo.sync_subscription("one", plan_id="basic", status="active", monthly_budget_cents=3000,
                                    stripe_subscription_id="sub-test", current_period_end=2_000_000_000)
        charge = self.repo.charge_usage("one", 150, "generation")
        self.assertEqual((charge.daily_cents, charge.wallet_cents, charge.beta_cents), (100, 50, 50))
        self.repo.refund_usage("one", charge, "failed")
        self.assertEqual(self.repo.get_balance("one"), 1000)
        self.assertEqual(self.repo.get_subscription_state("one")["daily_allowance_remaining_cents"], 100)

    def test_forged_beta_refund_is_refused(self):
        self.verify()
        self.beta.claim("one")
        with self.assertRaises(ValueError):
            self.repo.refund_usage("one", UsageCharge(0, 2000, "2026-10-09", beta_cents=2000), "forged")
        self.assertEqual(self.repo.get_balance("one"), 1000)

    def test_negative_cost_refused(self):
        with self.assertRaises(ValueError):
            self.repo.charge_usage("one", -10, "negative")
        self.assertEqual(self.repo.get_balance("one"), 0)

    def test_refund_cannot_discard_provenance_or_change_charge_date(self):
        self.verify()
        self.beta.claim("one")
        charge = self.repo.charge_usage("one", 250, "generation")
        for forged in (replace(charge, charge_id=None, beta_cents=0),
                       replace(charge, beta_cents=0),
                       replace(charge, charge_date="2099-01-01")):
            with self.assertRaises(ValueError):
                self.repo.refund_usage("one", forged, "forged")
        self.assertEqual(self.repo.get_balance("one"), 750)

    def test_beta_refund_recovers_durably_after_failure_without_duplicate_value(self):
        self.verify()
        self.beta.claim("one")
        charge = self.repo.charge_usage("one", 600, "generation")
        with patch.object(self.repo, "_apply_refund", side_effect=RuntimeError("temporary")):
            self.repo.refund_usage("one", charge, "failed")
            self.repo.refund_usage("one", charge, "retry")
        other = StudioRepository(self.repo.database_path, self.repo.media_root)
        self.assertEqual(other.get_balance("one"), 1000)
        self.assertEqual(other.get_beta_credit("one")["remaining_cents"], 1000)

    def test_concurrent_spending_and_refund_replay_is_bounded(self):
        self.verify()
        self.beta.claim("one")
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

    def test_salt_rotation_does_not_bypass_duplicate_identity(self):
        self.verify()
        self.beta.claim("one")
        self.configure(identity_salt="different-test-salt")
        self.assert_denied(lambda: self.beta.start_email("two", "one@example.com"),
                           "Beta identity configuration changed. Contact the operator.")

    def test_unique_constraints_block_either_identity_even_outside_service(self):
        self.verify()
        self.beta.claim("one")
        self.repo.ensure_account("two")
        grant = self.rows("SELECT * FROM beta_grants")[0]
        for email, phone in ((grant["email_hash"], "other-phone-hash"),
                             ("other-email-hash", grant["phone_hash"])):
            with self.assertRaises(sqlite3.IntegrityError), self.repo._connect() as connection:
                connection.execute(
                    "INSERT INTO beta_grants(id,user_id,email_hash,phone_hash,amount_cents,remaining_cents,wave,dry_run,created_at) "
                    "VALUES ('other','two',?,?,1000,1000,1,1,0)", (email, phone))

    def test_disabled_and_cap_zero_status_messages(self):
        self.configure(enabled=False, global_cap_cents=0)
        self.assertEqual(self.beta.get_beta_status()["message"], "Free beta credits are disabled.")
        self.assertEqual(self.beta.get_beta_status()["spots_left"], 0)

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

    def test_waitlist_only_records_email_hash_when_wave_full(self):
        self.configure(wave_size=0)
        self.beta.waitlist("one", "Private.Address+wait@gmail.com")
        dump = [dict(row) for row in self.rows("SELECT * FROM beta_waitlist")]
        self.assertEqual(len(dump[0]["email_hash"]), 64)
        self.assertNotIn("private", json.dumps(dump).lower())


class BetaApiTests(BetaFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from server import beta as api
        self.api = api
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[api.get_beta_credits] = lambda: self.beta
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "one"})
        self.app = app
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_status_public_exposes_only_counters_and_message(self):
        self.app.dependency_overrides[require_auth] = lambda: None
        response = self.client.get("/api/beta/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"enabled", "wave", "wave_size", "spots_left", "programme_full", "message"})
        self.assertNotIn("hash", json.dumps(response.json()))
        self.assertEqual(self.client.post("/api/beta/claim", json={}).status_code, 401)

    def test_route_verification_and_claim_flow(self):
        for kind, identifier, code_key, code in [("email", "one@example.com", "token", "beta-email-ok"),
                                                  ("phone", "+14165550101", "code", "424242")]:
            response = self.client.post(f"/api/beta/verify/{kind}/start", json={kind: identifier})
            self.assertEqual(response.status_code, 200)
            challenge = response.json()["challenge_id"]
            response = self.client.post(f"/api/beta/verify/{kind}/confirm", json={"challenge_id": challenge, code_key: code})
            self.assertEqual(response.status_code, 200)
        response = self.client.post("/api/beta/claim", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance_cents"], 1000)

    def test_ci_inventory_checks_the_mounted_application(self):
        with patch.dict("os.environ", {}), patch("builtins.print"):
            from scripts.ci_check import check_beta_inventory
            check_beta_inventory()

    def test_admin_token_required_and_wave_persists(self):
        with patch.dict("os.environ", {"BETA_ADMIN_TOKEN": ""}):
            self.assertEqual(self.client.post("/api/admin/beta/next-wave").status_code, 503)
        with patch.dict("os.environ", {"BETA_ADMIN_TOKEN": "test-admin-token"}):
            self.assertEqual(self.client.post("/api/admin/beta/next-wave").status_code, 403)
            self.assertEqual(self.client.post("/api/admin/beta/next-wave", headers={"X-Beta-Admin-Token": "wrong"}).status_code, 403)
            response = self.client.post("/api/admin/beta/next-wave", headers={"X-Beta-Admin-Token": "test-admin-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["wave"], 2)
        from server.beta_credits import BetaCredits
        self.assertEqual(BetaCredits(self.repo, self.settings).get_beta_status()["wave"], 2)

    def test_http_rate_limit_and_no_identity_reuse_disclosure(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/beta/verify/email/start", json={"email": "rate@example.com"}).status_code, 200)
        response = self.client.post("/api/beta/verify/email/start", json={"email": "rate@example.com"})
        self.assertEqual(response.status_code, 429)
        self.verify()
        self.beta.claim("one")
        self.verify("two", "one@example.com", "+14165550102")
        self.app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "two"})
        response = self.client.post("/api/beta/claim", json={})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Not eligible for free beta credit.")


class BetaBillingIntegrationTests(BetaFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.verify()
        self.beta.claim("one")
        self.enterContext(patch.dict("os.environ", {"STRIPE_SECRET_KEY": "", "BETA_CREDITS_ENABLED": "true"}))
        self.repo.create_project("user:one", "one", "Beta test", project_id="beta-project")

    async def test_studio_invocation_debits_and_rejects_when_free_credit_exhausted_without_stripe(self):
        from fastapi import HTTPException
        from server.studio import InvokeBody, invoke_tool
        body = InvokeBody(provider="seedream", tool="text_to_image", arguments={"prompt": "robot"}, project_id="beta-project")
        from server.billing_rates import GenerationCost
        with patch("server.studio.repository", self.repo), patch("server.studio.cost_for", return_value=GenerationCost(1000, 0)), \
                patch("server.studio.dispatch", return_value={"status": "dry_run"}):
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
        from server.studio import InvokeBody, invoke_tool
        from server.billing_rates import GenerationCost
        body = InvokeBody(provider="seedream", tool="text_to_image", arguments={"prompt": "robot"}, project_id="beta-project")
        for status in ("failed", "error", "blocked", "not_run"):
            with self.subTest(status=status), patch("server.studio.repository", self.repo), \
                    patch("server.studio.cost_for", return_value=GenerationCost(300, 0)), \
                    patch("server.studio.dispatch", return_value={"status": status, "reason": "No work performed."}):
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
