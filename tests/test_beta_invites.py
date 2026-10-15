from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.beta_credits import BetaError, BetaSettings
from server.beta_invites import (
    ALREADY_CLAIMED, EMAIL_TAKEN, INVITE_HELD, INVITE_INVALID, INVITE_USED, PROGRAMME_FULL, RATE_LIMITED, BetaInvites, normalize_code,
)
from server.studio_state import StudioRepository


class InviteFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name)
        self.repo = StudioRepository(path / "state.sqlite3", path / "media")
        self.settings = BetaSettings(enabled=True, global_cap_cents=50_000, wave_size=50,
                                     identity_salt="test-only-identity-salt")
        self.invites = BetaInvites(self.repo, self.settings)

    def denied(self, action, message):
        with self.assertRaises(BetaError) as caught:
            action()
        self.assertEqual(str(caught.exception), message)
        return caught.exception


def state_of(invites, code):
    return next(row["state"] for row in invites.list() if row["hint"] == f"…{code[-4:]}")


class InviteTests(InviteFixture, unittest.TestCase):
    def test_mint_stores_only_hashes_and_lists_by_hint(self):
        codes = self.invites.mint(3, "friends")
        self.assertEqual(len(set(codes)), 3)
        with self.repo._connect() as connection:
            stored = " ".join(str(tuple(row)) for row in connection.execute("SELECT * FROM beta_invites"))
        for code in codes:
            self.assertNotIn(code, stored)
        listed = self.invites.list()
        self.assertEqual({row["state"] for row in listed}, {"open"})
        self.assertEqual({row["label"] for row in listed}, {"friends"})

    def test_normalize_accepts_spacing_and_case(self):
        code = self.invites.mint()[0]
        self.assertEqual(normalize_code(code.lower().replace("-", " ")), code)
        self.assertEqual(normalize_code("nope"), "")

    def test_redeem_grants_ten_dollars_once(self):
        code = self.invites.mint()[0]
        result = self.invites.redeem("acct-1", code, email="a@example.com")
        self.assertEqual(result["balance_cents"], 1000)
        self.assertEqual(self.repo.get_beta_credit("acct-1")["remaining_cents"], 1000)
        self.denied(lambda: self.invites.redeem("acct-2", code, email="b@example.com"), INVITE_USED)
        self.assertEqual(self.repo.get_balance("acct-2"), 0)

    def test_one_grant_per_account_and_per_email(self):
        first, second, third = self.invites.mint(3)
        self.invites.redeem("acct-1", first, email="a@example.com")
        self.denied(lambda: self.invites.redeem("acct-1", second, email="a@example.com"), ALREADY_CLAIMED)
        self.denied(lambda: self.invites.redeem("acct-9", third, email="A+x@Example.com"), EMAIL_TAKEN)
        self.assertEqual(state_of(self.invites, third), "open")  # failed redeem does not burn the code
        self.assertEqual(state_of(self.invites, second), "open")

    def test_unknown_and_revoked_codes_are_invalid(self):
        code = self.invites.mint()[0]
        self.assertTrue(self.invites.revoke(code))
        self.assertFalse(self.invites.revoke(code))
        self.denied(lambda: self.invites.check(code, "1.1.1.1"), INVITE_INVALID)
        self.denied(lambda: self.invites.check("RH-AAAA-AAAA-AAAA", "1.1.1.1"), INVITE_INVALID)
        self.denied(lambda: self.invites.redeem("acct-1", code), INVITE_INVALID)

    def test_check_reserves_without_burning(self):
        code = self.invites.mint()[0]
        held = self.invites.check(code, "1.1.1.1")
        self.assertTrue(held["valid"])
        self.assertEqual(state_of(self.invites, code), "open")
        # Someone else can neither check nor redeem it while it is reserved.
        self.denied(lambda: self.invites.check(code, "2.2.2.2"), INVITE_HELD)
        self.denied(lambda: self.invites.redeem("acct-2", code), INVITE_USED)
        # The same browser re-checks (e.g. after a typo'd email) and still holds it.
        again = self.invites.check(code, "1.1.1.1", held["reservation"])
        self.assertEqual(again["reservation"], held["reservation"])
        self.assertEqual(self.invites.redeem("acct-1", code, held["reservation"], "a@example.com")["balance_cents"], 1000)
        self.assertEqual(state_of(self.invites, code), "redeemed")

    def test_expired_reservation_frees_the_code(self):
        code = self.invites.mint()[0]
        self.invites.check(code, "1.1.1.1")
        with self.repo._connect() as connection:
            connection.execute("UPDATE beta_invites SET reserved_until = 1")
        self.assertEqual(self.invites.redeem("acct-2", code)["balance_cents"], 1000)

    def test_check_is_rate_limited_per_ip(self):
        for _ in range(10):
            self.denied(lambda: self.invites.check("RH-AAAA-AAAA-AAAA", "9.9.9.9"), INVITE_INVALID)
        err = self.denied(lambda: self.invites.check("RH-AAAA-AAAA-AAAA", "9.9.9.9"), RATE_LIMITED)
        self.assertEqual(err.status_code, 429)
        self.denied(lambda: self.invites.check("RH-AAAA-AAAA-AAAA", "8.8.8.8"), INVITE_INVALID)

    def test_redeem_is_rate_limited_per_email(self):
        for index in range(5):
            self.denied(lambda: self.invites.redeem(f"acct-{index}", "RH-AAAA-AAAA-AAAA", email="x@example.com"), INVITE_INVALID)
        self.denied(lambda: self.invites.redeem("acct-new", "RH-AAAA-AAAA-AAAA", email="x@example.com"), RATE_LIMITED)

    def test_global_cap_still_applies(self):
        invites = BetaInvites(self.repo, BetaSettings(enabled=True, global_cap_cents=1500, identity_salt="test-only-identity-salt"))
        a, b = invites.mint(2)
        invites.redeem("acct-1", a)
        self.denied(lambda: invites.redeem("acct-2", b), PROGRAMME_FULL)
        self.assertEqual(state_of(invites, b), "open")

    def test_disabled_programme_grants_nothing(self):
        invites = BetaInvites(self.repo, BetaSettings(enabled=False))
        code = invites.mint()[0]
        self.denied(lambda: invites.redeem("acct-1", code), "Beta credits are disabled.")


class InviteApiTests(InviteFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from server import beta as api
        from server.billing import router as billing_router

        env = mock.patch.dict(os.environ, {"BETA_INVITE_ONLY": "true", "BETA_CREDITS_ENABLED": "true"})
        env.start()
        self.addCleanup(env.stop)
        app = FastAPI()
        app.include_router(api.router)
        app.include_router(billing_router)
        app.dependency_overrides[api.get_beta_invites] = lambda: self.invites
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={"sub": "acct-1", "email": "a@example.com"})
        self.app = app
        self.client = TestClient(app)

    def test_status_reports_invite_only_without_spot_copy(self):
        from server import beta as api
        from server.beta_credits import BetaCredits
        self.app.dependency_overrides[api.get_beta_credits] = lambda: BetaCredits(self.repo, self.settings)
        body = self.client.get("/api/beta/status").json()
        self.assertTrue(body["invite_only"])
        self.assertEqual(body["message"], "Invite only · $10 credit to start")

    def test_check_then_redeem(self):
        code = self.invites.mint()[0]
        checked = self.client.post("/api/beta/invite/check", json={"code": code}).json()
        self.assertTrue(checked["valid"])
        redeemed = self.client.post("/api/beta/invite/redeem", json={"code": code, "reservation": checked["reservation"]})
        self.assertEqual(redeemed.status_code, 200)
        self.assertEqual(redeemed.json()["balance_cents"], 1000)
        again = self.client.post("/api/beta/invite/check", json={"code": code})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, INVITE_USED))

    def test_check_rate_limit_uses_forwarded_ip(self):
        for _ in range(10):
            self.client.post("/api/beta/invite/check", json={"code": "RH-AAAA-AAAA-AAAA"}, headers={"X-Real-IP": "5.5.5.5"})
        blocked = self.client.post("/api/beta/invite/check", json={"code": "RH-AAAA-AAAA-AAAA"}, headers={"X-Real-IP": "5.5.5.5"})
        self.assertEqual(blocked.status_code, 429)

    def test_redeem_requires_sign_in(self):
        self.app.dependency_overrides[require_auth] = lambda: None
        code = self.invites.mint()[0]
        self.assertEqual(self.client.post("/api/beta/invite/redeem", json={"code": code}).status_code, 401)

    def test_phone_and_open_wave_routes_are_off(self):
        for path, body in (("/api/beta/verify/phone/start", {"phone": "+14165550101"}),
                           ("/api/beta/verify/email/start", {"email": "a@example.com"}),
                           ("/api/beta/claim", {}), ("/api/beta/hold", {}),
                           ("/api/beta/waitlist", {"email": "a@example.com"})):
            response = self.client.post(path, json=body)
            self.assertEqual(response.status_code, 403, path)

    def test_topups_blocked_server_side(self):
        for method, path in (("get", "/api/studio/billing/packs"), ("get", "/api/studio/billing/plans"),
                             ("post", "/api/studio/billing/checkout"), ("post", "/api/studio/billing/subscribe"),
                             ("post", "/api/studio/billing/portal"), ("post", "/api/studio/billing/webhook")):
            kwargs = {} if method == "get" else {"json": {"pack_id": "starter", "plan_id": "basic"}}
            response = getattr(self.client, method)(path, **kwargs)
            self.assertEqual((response.status_code, response.json()["detail"]), (403, "Top-ups are coming soon."), path)


class InviteCliTests(InviteFixture, unittest.TestCase):
    def test_mint_list_revoke(self):
        import contextlib
        import io

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "beta_invites_cli", Path(__file__).resolve().parents[1] / "scripts" / "beta_invites.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with mock.patch("server.studio_state.repository", self.repo), \
                mock.patch.dict(os.environ, {"BETA_IDENTITY_SALT": "test-only-identity-salt"}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(cli.main(["mint", "--count", "2", "--label", "t"]), 0)
            codes = out.getvalue().split()
            self.assertEqual(len(codes), 2)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["revoke", codes[0]]), 0)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["list"])
            self.assertIn('"revoked"', out.getvalue())
            self.assertNotIn(codes[1], out.getvalue())


if __name__ == "__main__":
    unittest.main()
