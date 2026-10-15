"""Invite-only beta: single-use invite codes, each worth one account + one grant.

Codes are minted and revoked by the operator CLI (``scripts/beta_invites.py``).
Only an HMAC of each code is stored; the plaintext is shown once at mint time.
Redeeming a code creates the account's one-time beta grant in the same
transaction that marks the code used, so a code can never fund two accounts
and an account can never take two grants. The global credit cap from
``BetaSettings`` still applies.
"""

from __future__ import annotations

import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from typing import TYPE_CHECKING

from server.beta_credits import BetaError, BetaSettings, identity_hash, normalize_email

if TYPE_CHECKING:
    from server.studio_state import StudioRepository

INVITE_INVALID = "We don't recognise that code. Check for typos, or ask the person who invited you to send it again."
INVITE_USED = ("This code has already been used. Each code works once. If it was you, sign in with your email. "
               "If not, ask for a new code.")
RATE_LIMITED = "Too many tries. Wait a few minutes and try again."
EMAIL_TAKEN = "This email already has an account. Sign in with your email."
RESERVE_SECONDS = 30 * 60
RATE_WINDOW_SECONDS = 15 * 60
CHECK_LIMIT_PER_IP = 10
REDEEM_LIMIT = 5
INVITE_ONLY = "Renderhaus is invite only right now."
INVITE_HELD = ("This code is in the middle of a sign-up in another browser or tab. Finish there, "
               "or try again here in about 30 minutes.")
ALREADY_CLAIMED = "This account already has its beta credit."
PROGRAMME_FULL = "The beta credit is fully allocated."
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_RE = re.compile(r"RH-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}")


def invite_only_enabled() -> bool:
    raw = os.environ.get("BETA_INVITE_ONLY", "false").strip().lower()
    if raw not in {"true", "false", "1", "0"}:
        raise ValueError("BETA_INVITE_ONLY must be true or false.")
    return raw in {"true", "1"}


def normalize_code(code: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", code.strip().upper())
    if cleaned.startswith("RH"):
        cleaned = cleaned[2:]
    if len(cleaned) != 12:
        return ""
    candidate = f"RH-{cleaned[0:4]}-{cleaned[4:8]}-{cleaned[8:12]}"
    return candidate if _CODE_RE.fullmatch(candidate) else ""


def new_code() -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"RH-{body[0:4]}-{body[4:8]}-{body[8:12]}"


def init_invite_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS beta_invites (
            code_hash TEXT PRIMARY KEY,
            code_hint TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            revoked_at INTEGER,
            redeemed_by TEXT UNIQUE,
            redeemed_at INTEGER,
            reservation_hash TEXT,
            reserved_until INTEGER
        );
        CREATE TABLE IF NOT EXISTS beta_invite_attempts (
            key_hash TEXT NOT NULL,
            window INTEGER NOT NULL,
            attempts INTEGER NOT NULL,
            PRIMARY KEY(key_hash, window)
        );
    """)


class BetaInvites:
    def __init__(self, repository: StudioRepository, settings: BetaSettings):
        self.repository = repository
        self.settings = settings
        self.salt = settings.identity_salt or "renderhaus-beta-dry-run-only"
        repository.init()
        with repository._connect() as connection:
            init_invite_schema(connection)

    def _hash(self, code: str) -> str:
        return identity_hash("invite", code, self.salt)

    # Operator actions -------------------------------------------------------------
    def mint(self, count: int = 1, label: str = "") -> list[str]:
        if not 1 <= count <= 500:
            raise ValueError("count must be between 1 and 500.")
        codes: list[str] = []
        now = int(time.time())
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            while len(codes) < count:
                code = new_code()
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO beta_invites(code_hash, code_hint, label, created_at) VALUES (?, ?, ?, ?)",
                    (self._hash(code), code[-4:], label[:80], now),
                )
                if cursor.rowcount:
                    codes.append(code)
        return codes

    def revoke(self, code: str) -> bool:
        normalized = normalize_code(code)
        if not normalized:
            return False
        with self.repository._connect() as connection:
            cursor = connection.execute(
                "UPDATE beta_invites SET revoked_at = ? WHERE code_hash = ? AND revoked_at IS NULL AND redeemed_by IS NULL",
                (int(time.time()), self._hash(normalized)),
            )
            return cursor.rowcount == 1

    def list(self) -> list[dict]:
        with self.repository._connect() as connection:
            rows = connection.execute("SELECT * FROM beta_invites ORDER BY created_at, code_hint").fetchall()
        out = []
        for row in rows:
            state = "revoked" if row["revoked_at"] else "redeemed" if row["redeemed_by"] else "open"
            out.append({"hint": f"…{row['code_hint']}", "label": row["label"], "state": state,
                        "created_at": row["created_at"], "redeemed_at": row["redeemed_at"]})
        return out

    # User actions -----------------------------------------------------------------
    def _limit(self, connection: sqlite3.Connection, scope: str, key: str, limit: int) -> None:
        window = int(time.time()) // RATE_WINDOW_SECONDS
        key_hash = identity_hash("invite-rate", f"{scope}:{key}", self.salt)
        connection.execute(
            "INSERT INTO beta_invite_attempts VALUES (?, ?, 1) "
            "ON CONFLICT(key_hash, window) DO UPDATE SET attempts = attempts + 1",
            (key_hash, window),
        )
        connection.execute("DELETE FROM beta_invite_attempts WHERE window < ?", (window - 1,))
        attempts = connection.execute(
            "SELECT attempts FROM beta_invite_attempts WHERE key_hash = ? AND window = ?", (key_hash, window)
        ).fetchone()[0]
        if attempts > limit:
            raise BetaError(RATE_LIMITED, 429)

    def _lookup(self, connection: sqlite3.Connection, normalized: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM beta_invites WHERE code_hash = ?", (self._hash(normalized),)
        ).fetchone() if normalized else None
        if row is None or row["revoked_at"]:
            raise BetaError(INVITE_INVALID, 400)
        if row["redeemed_by"]:
            raise BetaError(INVITE_USED, 409)
        return row

    def check(self, code: str, client_ip: str, reservation: str = "") -> dict:
        """Validate a code and reserve it (not burn it) for 30 minutes.

        The code is only marked used by ``redeem`` once the email is confirmed, so a
        typo'd email never costs the code. The reservation token lets the same browser
        finish while stopping a second person from using the code meanwhile."""
        normalized = normalize_code(code)
        error: BetaError | None = None
        result: dict = {}
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._limit(connection, "ip", client_ip or "unknown", CHECK_LIMIT_PER_IP)
                row = self._lookup(connection, normalized)
                now = int(time.time())
                token_hash = identity_hash("reservation", reservation, self.salt) if reservation else ""
                held = row["reserved_until"] and row["reserved_until"] > now
                if held and not (token_hash and hmac.compare_digest(token_hash, row["reservation_hash"] or "")):
                    raise BetaError(INVITE_HELD, 423)
                if not token_hash:
                    reservation = secrets.token_urlsafe(24)
                    token_hash = identity_hash("reservation", reservation, self.salt)
                connection.execute(
                    "UPDATE beta_invites SET reservation_hash = ?, reserved_until = ? WHERE code_hash = ?",
                    (token_hash, now + RESERVE_SECONDS, row["code_hash"]),
                )
                result = {"valid": True, "reservation": reservation, "reserved_until": now + RESERVE_SECONDS,
                          "credit_cents": self.settings.grant_cents}
            except BetaError as exc:
                error = exc
            # Commit the attempt counter even when the check fails.
        if error:
            raise error
        return result

    def redeem(self, account: str, code: str, reservation: str = "", email: str = "") -> dict:
        """Burn the code and grant the one-time credit. Call only after the account's
        email is confirmed (the signed-in session proves it)."""
        if not self.settings.enabled:
            raise BetaError("Beta credits are disabled.", 403)
        normalized = normalize_code(code)
        error: BetaError | None = None
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._limit(connection, "account", account, REDEEM_LIMIT)
                email_key = normalize_email(email) if email else ""
                if email_key:
                    self._limit(connection, "email", email_key, REDEEM_LIMIT)
            except (BetaError, ValueError) as exc:
                error = exc if isinstance(exc, BetaError) else BetaError(str(exc), 400)
        if error:
            raise error
        identity = identity_hash("email", email_key, self.salt) if email_key else identity_hash("account", account, self.salt)
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute("SELECT * FROM beta_grants WHERE user_id = ?", (account,)).fetchone()
                if existing:
                    raise BetaError(ALREADY_CLAIMED, 409)
                if connection.execute("SELECT 1 FROM beta_grants WHERE email_hash = ?", (identity,)).fetchone():
                    raise BetaError(EMAIL_TAKEN, 409)
                invite = self._lookup(connection, normalized)
                code_hash = invite["code_hash"]
                now = int(time.time())
                if invite["reserved_until"] and invite["reserved_until"] > now:
                    token_hash = identity_hash("reservation", reservation, self.salt) if reservation else ""
                    if not hmac.compare_digest(token_hash, invite["reservation_hash"] or ""):
                        raise BetaError(INVITE_USED, 409)
                committed = connection.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM beta_grants").fetchone()[0]
                if committed + self.settings.grant_cents > self.settings.global_cap_cents:
                    raise BetaError(PROGRAMME_FULL, 403)
                claimed = connection.execute(
                    "UPDATE beta_invites SET redeemed_by = ?, redeemed_at = ?, reserved_until = NULL "
                    "WHERE code_hash = ? AND revoked_at IS NULL AND redeemed_by IS NULL",
                    (account, now, code_hash),
                )
                if claimed.rowcount != 1:
                    raise BetaError(INVITE_USED, 409)
                wave = connection.execute("SELECT wave FROM beta_programme WHERE id = 1").fetchone()
                wave_index = wave["wave"] if wave else self.settings.wave_index
                grant_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT OR IGNORE INTO accounts(user_id, balance_cents, created_at, updated_at) VALUES (?, 0, ?, ?)",
                    (account, now, now),
                )
                # email_hash/phone_hash are NOT NULL UNIQUE in the existing schema; for invite
                # grants the email (or account) and the invite are the unique identities.
                connection.execute(
                    "INSERT INTO beta_grants(id, user_id, email_hash, phone_hash, amount_cents, remaining_cents, wave, dry_run, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (grant_id, account, identity, f"invite:{code_hash}",
                     self.settings.grant_cents, self.settings.grant_cents, wave_index, now),
                )
                self.repository._apply_balance_delta(connection, account, self.settings.grant_cents, now)
                connection.execute(
                    "INSERT INTO credit_ledger VALUES (?, ?, ?, 'beta_grant', ?, ?)",
                    (uuid.uuid4().hex, account, self.settings.grant_cents, f"beta:{grant_id}", now),
                )
            except BetaError as exc:
                error = exc
                connection.rollback()
            balance = connection.execute("SELECT balance_cents FROM accounts WHERE user_id = ?", (account,)).fetchone()
        if error:
            raise error
        return {"balance_cents": balance[0] if balance else 0,
                "grant": {"amount_cents": self.settings.grant_cents},
                "message": "You're in · $10 credit added"}
