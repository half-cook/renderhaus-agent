#!/usr/bin/env python3
"""Operator CLI for invite-only beta codes.

  python scripts/beta_invites.py mint --count 5 --label "friends"
  python scripts/beta_invites.py revoke RH-XXXX-XXXX-XXXX
  python scripts/beta_invites.py list

Each code is single use: one account, one $10 grant. Plaintext codes are printed
once at mint time and never stored (only an HMAC keyed by BETA_IDENTITY_SALT).
Run it on the app host against the same STUDIO database the server uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    from server.beta_credits import BetaSettings
    from server.beta_invites import BetaInvites
    from server.studio_state import repository

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    mint = sub.add_parser("mint", help="create single-use invite codes")
    mint.add_argument("--count", type=int, default=1)
    mint.add_argument("--label", default="", help="who the codes are for (kept with the code)")
    revoke = sub.add_parser("revoke", help="revoke an unused code")
    revoke.add_argument("code")
    sub.add_parser("list", help="list codes by last four characters and state")
    args = parser.parse_args(argv)

    invites = BetaInvites(repository, BetaSettings.from_env())
    if args.command == "mint":
        for code in invites.mint(args.count, args.label):
            print(code)
        return 0
    if args.command == "revoke":
        if invites.revoke(args.code):
            print("revoked")
            return 0
        print("not revoked: unknown, already used, or already revoked", file=sys.stderr)
        return 1
    print(json.dumps(invites.list(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
