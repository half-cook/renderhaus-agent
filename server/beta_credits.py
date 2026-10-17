from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.studio_state import StudioRepository

class BetaError(ValueError):
    def __init__(self, message: str, status_code: int = 403):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class BetaSettings:
    enabled: bool = False
    grant_cents: int = 1000
    global_cap_cents: int = 0
    wave_index: int = 1
    identity_salt: str = field(default="", repr=False)

    def __post_init__(self):
        for name, minimum in (("grant_cents", 1), ("global_cap_cents", 0),
                              ("wave_index", 1)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= 2**63 - 1:
                raise ValueError(f"BETA_{name.upper()} must be an integer between {minimum} and {2**63 - 1}.")

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
            global_cap_cents=integer("BETA_GLOBAL_CAP_CENTS", 50000),
            wave_index=integer("BETA_WAVE_INDEX", 1),
            identity_salt=os.environ.get("BETA_IDENTITY_SALT", ""),
        )


def beta_billing_enabled(repository: StudioRepository, user_id: str) -> bool:
    """Credit is metered for beta accounts, every invite-only account, and any prepaid balance.

    The first live run granted $5 directly (no beta grant row, Stripe off), so this gate
    returned False and approved paid steps ran free while the balance stayed $5.00.
    """
    if BetaSettings.from_env().enabled or repository.get_beta_credit(user_id) is not None:
        return True
    try:
        from server.beta_invites import invite_only_enabled

        if invite_only_enabled():
            return True
    except (ImportError, ValueError):
        return True  # misconfigured invite-only flag: fail closed and meter
    return repository.get_balance(user_id) > 0


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


def identity_hash(kind: str, normalized: str, salt: str) -> str:
    return hmac.new(salt.encode(), f"{kind}:{normalized}".encode(), hashlib.sha256).hexdigest()


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
        CREATE TABLE IF NOT EXISTS beta_holds (
            user_id TEXT PRIMARY KEY,
            wave INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
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
