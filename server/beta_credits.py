from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from server.studio_state import StudioRepository

logger = logging.getLogger(__name__)
DISABLED = "Free beta credits are disabled."
PROGRAMME_FULL = "The free beta credit is fully allocated."
WAVE_FULL = "This wave is full. Join the waitlist for the next one."
NOT_ELIGIBLE = "Not eligible for free beta credit."
VERIFICATION_UNAVAILABLE = "Beta verification is unavailable."
VERIFICATION_FAILED = "Verification could not be confirmed."
RATE_LIMITED = "Too many verification attempts. Try again later."
DAILY_LIMIT = "Today's beta grant limit has been reached. Try again tomorrow."
RATE_WINDOW_SECONDS = 15 * 60
CHALLENGE_TTL_SECONDS = 10 * 60
IdentityKind = Literal["email", "phone"]


class BetaError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class BetaSettings:
    enabled: bool = False
    grant_cents: int = 1000
    global_cap_cents: int = 0
    wave_size: int = 0
    wave_index: int = 1
    daily_grant_limit: int = 0
    verification_dry_run: bool = True
    identity_salt: str = field(default="", repr=False)

    def __post_init__(self):
        for name, minimum in (("grant_cents", 1), ("global_cap_cents", 0), ("wave_size", 0),
                              ("wave_index", 1), ("daily_grant_limit", 0)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= 2**63 - 1:
                raise ValueError(f"BETA_{name.upper()} must be an integer between {minimum} and {2**63 - 1}.")
        if self.enabled and not self.verification_dry_run and not self.identity_salt.strip():
            raise ValueError("BETA_IDENTITY_SALT is required for non-dry-run beta verification.")

    @classmethod
    def from_env(cls) -> BetaSettings:
        def integer(name: str, default: int) -> int:
            raw = os.environ.get(name, str(default))
            if not re.fullmatch(r"[0-9]+", raw):
                raise ValueError(f"{name} must be an integer.")
            return int(raw)

        def boolean(name: str, default: bool) -> bool:
            raw = os.environ.get(name, str(default)).lower()
            if raw not in {"true", "false", "1", "0"}:
                raise ValueError(f"{name} must be true or false.")
            return raw in {"true", "1"}

        return cls(
            enabled=boolean("BETA_CREDITS_ENABLED", False),
            grant_cents=integer("BETA_GRANT_CENTS", 1000),
            global_cap_cents=integer("BETA_GLOBAL_CAP_CENTS", 0),
            wave_size=integer("BETA_WAVE_SIZE", 0),
            wave_index=integer("BETA_WAVE_INDEX", 1),
            daily_grant_limit=integer("BETA_DAILY_GRANT_LIMIT", 0),
            verification_dry_run=boolean("BETA_VERIFICATION_DRY_RUN", True),
            identity_salt=os.environ.get("BETA_IDENTITY_SALT", ""),
        )


def beta_billing_enabled(repository: StudioRepository, user_id: str) -> bool:
    return BetaSettings.from_env().enabled or repository.get_beta_credit(user_id) is not None


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or not re.fullmatch(r"[^\s@+]+(?:\+[^\s@]*)?@[^\s@]+\.[^\s@]+", normalized):
        raise ValueError("Enter a valid email address.")
    local, domain = normalized.split("@")
    local = local.split("+", 1)[0]
    if domain in {"gmail.com", "googlemail.com"}:
        domain = "gmail.com"
        local = local.replace(".", "")
    if not local:
        raise ValueError("Enter a valid email address.")
    return f"{local}@{domain}"


def normalize_phone(phone: str) -> str:
    normalized = re.sub(r"[ ()\-]", "", phone.strip())
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", normalized):
        raise ValueError("Enter a phone number in E.164 format, including the country code.")
    return normalized


def identity_hash(kind: str, normalized: str, salt: str) -> str:
    return hmac.new(salt.encode(), f"{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class VerificationChallenge:
    identifier_hash: str
    reference: str


class VerificationProvider(Protocol):
    dry_run: bool

    def start_email(self, email: str) -> VerificationChallenge: ...
    def confirm_email(self, token: str) -> str: ...
    def start_phone(self, phone: str) -> VerificationChallenge: ...
    def confirm_phone(self, code: str) -> str: ...


class DryRunVerificationProvider:
    dry_run = True

    def __init__(self, salt: str):
        self.salt = salt

    def start_email(self, email: str) -> VerificationChallenge:
        digest = identity_hash("email", normalize_email(email), self.salt)
        return VerificationChallenge(digest, digest)

    def start_phone(self, phone: str) -> VerificationChallenge:
        digest = identity_hash("phone", normalize_phone(phone), self.salt)
        return VerificationChallenge(digest, digest)

    def _confirm(self, proof: str, expected: str) -> str:
        digest, _, code = proof.partition(":")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not hmac.compare_digest(code.encode(), expected.encode()):
            raise BetaError(VERIFICATION_FAILED, 400)
        return digest

    def confirm_email(self, token: str) -> str:
        return self._confirm(token, "beta-email-ok")

    def confirm_phone(self, code: str) -> str:
        return self._confirm(code, "424242")


def init_beta_schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS beta_programme (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            wave INTEGER NOT NULL CHECK(wave > 0),
            salt_fingerprint TEXT
        );
        CREATE TABLE IF NOT EXISTS beta_grants (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL UNIQUE REFERENCES accounts(user_id),
            email_hash TEXT NOT NULL UNIQUE,
            phone_hash TEXT NOT NULL UNIQUE,
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            remaining_cents INTEGER NOT NULL CHECK(remaining_cents >= 0 AND remaining_cents <= amount_cents),
            spent_cents INTEGER NOT NULL DEFAULT 0 CHECK(spent_cents = amount_cents - remaining_cents),
            gross_spent_cents INTEGER NOT NULL DEFAULT 0 CHECK(gross_spent_cents >= spent_cents),
            wave INTEGER NOT NULL,
            dry_run INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS beta_grants_wave ON beta_grants(wave);
        CREATE INDEX IF NOT EXISTS beta_grants_created ON beta_grants(created_at);
        CREATE TABLE IF NOT EXISTS beta_verifications (
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('email', 'phone')),
            challenge_id TEXT NOT NULL UNIQUE,
            identifier_hash TEXT NOT NULL,
            provider_reference TEXT NOT NULL,
            dry_run INTEGER NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            expires_at INTEGER NOT NULL,
            PRIMARY KEY(user_id, kind)
        );
        CREATE TABLE IF NOT EXISTS beta_rate_limits (
            key_hash TEXT NOT NULL,
            window INTEGER NOT NULL,
            attempts INTEGER NOT NULL,
            PRIMARY KEY(key_hash, window)
        );
        CREATE TABLE IF NOT EXISTS beta_waitlist (
            email_hash TEXT PRIMARY KEY,
            wave INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS beta_audit (
            id TEXT PRIMARY KEY,
            account_prefix TEXT NOT NULL,
            email_prefix TEXT NOT NULL,
            phone_prefix TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
    """)


class BetaCredits:
    def __init__(self, repository: StudioRepository, settings: BetaSettings,
                 provider: VerificationProvider | None = None):
        self.repository = repository
        self.settings = settings
        self.salt = settings.identity_salt or "renderhaus-beta-dry-run-only"
        self.provider = DryRunVerificationProvider(self.salt) if settings.verification_dry_run else provider
        repository.init()

    def _require_provider(self) -> VerificationProvider:
        if self.provider is None or (not self.settings.verification_dry_run and self.provider.dry_run):
            raise BetaError(VERIFICATION_UNAVAILABLE, 503)
        return self.provider

    def _enabled(self) -> None:
        if not self.settings.enabled:
            raise BetaError(DISABLED)

    def _programme(self, connection: sqlite3.Connection) -> sqlite3.Row:
        connection.execute("INSERT OR IGNORE INTO beta_programme(id, wave) VALUES (1, ?)", (self.settings.wave_index,))
        return connection.execute("SELECT * FROM beta_programme WHERE id = 1").fetchone()

    def _bind_salt(self, connection: sqlite3.Connection) -> None:
        row = self._programme(connection)
        fingerprint = identity_hash("salt", "beta-programme", self.salt)
        if row["salt_fingerprint"] and row["salt_fingerprint"] != fingerprint:
            raise BetaError("Beta identity configuration changed. Contact the operator.", 503)
        connection.execute("UPDATE beta_programme SET salt_fingerprint = ? WHERE id = 1", (fingerprint,))

    def _status(self, connection: sqlite3.Connection) -> dict:
        wave = self._programme(connection)["wave"]
        committed, admitted = connection.execute(
            "SELECT COALESCE(SUM(amount_cents), 0), COUNT(CASE WHEN wave = ? THEN 1 END) FROM beta_grants", (wave,)
        ).fetchone()
        capacity = max(0, (self.settings.global_cap_cents - committed) // self.settings.grant_cents)
        full = capacity == 0
        spots = min(max(0, self.settings.wave_size - admitted), capacity) if self.settings.enabled else 0
        message = DISABLED if not self.settings.enabled else PROGRAMME_FULL if full else WAVE_FULL if spots == 0 else f"{spots} spots left in this wave"
        return {"enabled": self.settings.enabled, "wave": wave, "wave_size": self.settings.wave_size,
                "spots_left": spots, "programme_full": full, "message": message}

    def get_beta_status(self) -> dict:
        with self.repository._connect() as connection:
            return self._status(connection)

    def _rate_limit(self, connection: sqlite3.Connection, account: str, kind: str, digest: str) -> None:
        window = int(time.time()) // RATE_WINDOW_SECONDS
        keys = [(identity_hash("account", account, self.salt), 10),
                (identity_hash(kind, digest, self.salt), 5)]
        connection.execute("DELETE FROM beta_rate_limits WHERE window < ?", (window - 1,))
        limited = False
        for key, maximum in keys:
            connection.execute(
                "INSERT INTO beta_rate_limits(key_hash, window, attempts) VALUES (?, ?, 1) "
                "ON CONFLICT(key_hash, window) DO UPDATE SET attempts = MIN(attempts + 1, 1000000)", (key, window)
            )
            count = connection.execute("SELECT attempts FROM beta_rate_limits WHERE key_hash = ? AND window = ?", (key, window)).fetchone()[0]
            limited |= count > maximum
        if limited:
            raise BetaError(RATE_LIMITED, 429)

    def _audit(self, connection: sqlite3.Connection, account: str, outcome: str, reason: str,
               email: str = "", phone: str = "") -> None:
        prefixes = (identity_hash("account", account, self.salt)[:12], email[:12], phone[:12])
        connection.execute(
            "INSERT INTO beta_audit VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, *prefixes, outcome, reason, int(time.time()))
        )
        logger.info("beta outcome=%s reason=%s account=%s email=%s phone=%s", outcome, reason, *prefixes)

    def _start(self, account: str, kind: IdentityKind, identifier: str) -> dict:
        self._enabled()
        provider = self._require_provider()
        normalized = normalize_email(identifier) if kind == "email" else normalize_phone(identifier)
        digest = identity_hash(kind, normalized, self.salt)
        error = None
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bind_salt(connection)
            try:
                self._rate_limit(connection, account, kind, digest)
            except BetaError as exc:
                error = exc
            if error is None:
                challenge = provider.start_email(normalized) if kind == "email" else provider.start_phone(normalized)
                if challenge.identifier_hash != digest:
                    raise BetaError(VERIFICATION_UNAVAILABLE, 503)
                challenge_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO beta_verifications VALUES (?, ?, ?, ?, ?, ?, 0, ?) "
                    "ON CONFLICT(user_id, kind) DO UPDATE SET challenge_id = excluded.challenge_id, "
                    "identifier_hash = excluded.identifier_hash, provider_reference = excluded.provider_reference, "
                    "dry_run = excluded.dry_run, verified = 0, expires_at = excluded.expires_at",
                    (account, kind, challenge_id, digest, challenge.reference, int(provider.dry_run), int(time.time()) + CHALLENGE_TTL_SECONDS)
                )
        if error:
            raise error
        message = "Verification started."
        if provider.dry_run:
            code = "beta-email-ok" if kind == "email" else "424242"
            message = f"Mock verification. No message was sent. Use {code}."
        return {"challenge_id": challenge_id, "dry_run": provider.dry_run, "message": message}

    def start_email(self, account: str, email: str) -> dict:
        return self._start(account, "email", email)

    def start_phone(self, account: str, phone: str) -> dict:
        return self._start(account, "phone", phone)

    def _confirm(self, account: str, kind: IdentityKind, challenge_id: str, code: str) -> dict:
        self._enabled()
        provider = self._require_provider()
        error = None
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bind_salt(connection)
            row = connection.execute("SELECT * FROM beta_verifications WHERE user_id = ? AND kind = ?", (account, kind)).fetchone()
            try:
                self._rate_limit(connection, account, kind, row["identifier_hash"] if row else "missing")
                if not row or row["challenge_id"] != challenge_id or row["expires_at"] < int(time.time()) or bool(row["dry_run"]) != provider.dry_run:
                    raise BetaError(VERIFICATION_FAILED, 400)
                proof = f"{row['provider_reference']}:{code}"
                digest = provider.confirm_email(proof) if kind == "email" else provider.confirm_phone(proof)
                if not hmac.compare_digest(digest.encode(), row["identifier_hash"].encode()):
                    raise BetaError(VERIFICATION_FAILED, 400)
                connection.execute("UPDATE beta_verifications SET verified = 1 WHERE challenge_id = ?", (challenge_id,))
            except BetaError as exc:
                error = exc
        if error:
            raise error
        return {"verified": True, "message": f"{kind.capitalize()} verified."}

    def confirm_email(self, account: str, challenge_id: str, token: str) -> dict:
        return self._confirm(account, "email", challenge_id, token)

    def confirm_phone(self, account: str, challenge_id: str, code: str) -> dict:
        return self._confirm(account, "phone", challenge_id, code)

    def claim(self, account: str) -> dict:
        error = None
        email = phone = ""
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._enabled()
                self._bind_salt(connection)
                grant = connection.execute("SELECT * FROM beta_grants WHERE user_id = ?", (account,)).fetchone()
                if grant:
                    self._audit(connection, account, "idempotent", "existing_grant", grant["email_hash"], grant["phone_hash"])
                else:
                    status = self._status(connection)
                    if status["programme_full"] or status["spots_left"] == 0:
                        raise BetaError(status["message"])
                    provider = self._require_provider()
                    identities = {row["kind"]: row for row in connection.execute(
                        "SELECT * FROM beta_verifications WHERE user_id = ? AND verified = 1 AND dry_run = ?", (account, int(provider.dry_run))
                    )}
                    email = identities["email"]["identifier_hash"] if "email" in identities else ""
                    phone = identities["phone"]["identifier_hash"] if "phone" in identities else ""
                    if not email or not phone:
                        raise BetaError(NOT_ELIGIBLE)
                    duplicate = connection.execute("SELECT 1 FROM beta_grants WHERE email_hash = ? OR phone_hash = ?", (email, phone)).fetchone()
                    if duplicate:
                        self._audit(connection, account, "denied", "identity_reused", email, phone)
                        error = BetaError(NOT_ELIGIBLE)
                    else:
                        now = int(time.time())
                        today_start = now - now % (24 * 3600)
                        granted_today = connection.execute("SELECT COUNT(*) FROM beta_grants WHERE created_at >= ?", (today_start,)).fetchone()[0]
                        if self.settings.daily_grant_limit and granted_today >= self.settings.daily_grant_limit:
                            raise BetaError(DAILY_LIMIT)
                        grant_id = uuid.uuid4().hex
                        connection.execute("INSERT OR IGNORE INTO accounts(user_id, balance_cents, created_at, updated_at) VALUES (?, 0, ?, ?)", (account, now, now))
                        connection.execute(
                            "INSERT INTO beta_grants(id, user_id, email_hash, phone_hash, amount_cents, remaining_cents, wave, dry_run, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (grant_id, account, email, phone, self.settings.grant_cents, self.settings.grant_cents, status["wave"], int(provider.dry_run), now)
                        )
                        self.repository._apply_balance_delta(connection, account, self.settings.grant_cents, now)
                        connection.execute("INSERT INTO credit_ledger VALUES (?, ?, ?, 'beta_grant', ?, ?)", (uuid.uuid4().hex, account, self.settings.grant_cents, f"beta:{grant_id}", now))
                        self._audit(connection, account, "granted", "beta_grant", email, phone)
                        grant = connection.execute("SELECT * FROM beta_grants WHERE id = ?", (grant_id,)).fetchone()
            except BetaError as exc:
                error = exc
                self._audit(connection, account, "denied", str(exc), email, phone)
            balance = connection.execute("SELECT balance_cents FROM accounts WHERE user_id = ?", (account,)).fetchone()
        if error:
            raise error
        return {"balance_cents": balance[0], "grant": {"amount_cents": grant["amount_cents"], "wave": grant["wave"]},
                "message": "Your free beta credit is ready."}

    def waitlist(self, account: str, email: str) -> dict:
        self._enabled()
        digest = identity_hash("email", normalize_email(email), self.salt)
        error = None
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bind_salt(connection)
            try:
                self._rate_limit(connection, account, "email", digest)
                status = self._status(connection)
                if status["programme_full"] or status["spots_left"] > 0:
                    raise BetaError("The waitlist is available when this wave is full.", 409)
                connection.execute("INSERT OR IGNORE INTO beta_waitlist VALUES (?, ?, ?)", (digest, status["wave"], int(time.time())))
            except BetaError as exc:
                error = exc
        if error:
            raise error
        return {"message": "You joined the waitlist. No email was sent."}

    def next_wave(self) -> dict:
        self._enabled()
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._programme(connection)
            connection.execute("UPDATE beta_programme SET wave = wave + 1 WHERE id = 1")
            self._audit(connection, "operator", "wave_opened", "next_wave")
            return self._status(connection)
