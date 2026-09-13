#!/usr/bin/env python3
"""Codex lifecycle gate for agent-performed browser checks; never handles credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
APP_ROOTS = ("agent/", "server/", "providers/", "lambdas/", "studio/", "remotion/", "configs/", "web/")
APP_FILES = {"pyproject.toml", "uv.lock", "Dockerfile", "Dockerfile.agentcore"}


def fingerprint(root: Path) -> str:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        if not (name.startswith(APP_ROOTS) or name in APP_FILES) or name.endswith(".md"):
            continue
        path = root / name
        digest.update(name.encode() + b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b"deleted")
    return digest.hexdigest()


def state_path(root: Path, session: str) -> Path:
    key = hashlib.sha256(session.encode()).hexdigest()[:32]
    return root / ".renderhaus" / "e2e" / "hooks" / f"{key}.json"


def read_state(root: Path, session: str) -> dict:
    path = state_path(root, session)
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(root: Path, session: str, state: dict) -> None:
    path = state_path(root, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def guidance(session: str) -> str:
    return (
        "Browser E2E is required after app behavior changes. Follow AGENTS.md and "
        "docs/BROWSER_E2E.md. Use Perplexity Comet and its existing signed-in session. "
        "Do not silently substitute the in-app browser. Start/restart the real backend and "
        "frontend, then use browser "
        "tools to reproduce the affected flow and observe its final result. Unit tests and "
        "HTTP 200 are insufficient. If authentication is needed, show the login tab and ask "
        "the user to log in; keep E2E pending while waiting. Do not collect credentials, "
        "bypass auth, or exceed existing action/spending authorization. Record actual browser "
        "observations in .renderhaus/e2e/report.json, then run: "
        "python3 scripts/browser_e2e_hook.py record --session "
        + shlex.quote(session)
        + " --report .renderhaus/e2e/report.json. Report status must be passed, waiting_login, "
        "or blocked. Never claim E2E passed when it is incomplete."
    )


def handle_event(root: Path, event: dict) -> dict:
    session = event.get("session_id")
    if not session or event.get("permission_mode") == "plan":
        return {}
    current = fingerprint(root)
    state = read_state(root, session)
    state.setdefault("baseline", current)
    state["pending"] = state.get("pending", False) or current != state["baseline"]
    name = event.get("hook_event_name")
    if name == "UserPromptSubmit":
        state["turn_id"] = event.get("turn_id")
        # Login/external blockers permit a handoff, but must be revisited next turn.
        if state.get("receipt", {}).get("status") != "passed":
            state.pop("receipt", None)
        save_state(root, session, state)
        return {"hookSpecificOutput": {
            "hookEventName": name,
            "additionalContext": guidance(session),
        }}
    if name != "Stop":
        return {}
    receipt = state.get("receipt", {})
    if receipt.get("fingerprint") == current:
        if receipt.get("status") == "passed":
            state.update(baseline=current, pending=False)
        elif receipt.get("turn_id") == state.get("turn_id"):
            save_state(root, session, state)
            return {"systemMessage": "Browser E2E remains pending: " + receipt["observed"]}
    save_state(root, session, state)
    if not state["pending"]:
        return {}
    if event.get("stop_hook_active"):
        # Avoid endless forced turns if login or browser tooling is unavailable.
        # Keep the requirement pending for the next user turn; this is not a pass.
        return {"systemMessage": (
            "Browser E2E evidence is still missing. Validation is incomplete; "
            "do not treat unit tests or this hook's exit as E2E success."
        )}
    return {"decision": "block", "reason": guidance(session)}


def record(root: Path, session: str, report: dict) -> None:
    if report.get("status") not in {"passed", "waiting_login", "blocked"}:
        raise ValueError("status must be passed, waiting_login, or blocked")
    for field in ("scenario", "url", "expected", "observed"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            raise ValueError(f"{field} must describe the actual browser check")
    url = urlsplit(report["url"])
    if url.scheme not in {"http", "https"} or not url.hostname or url.query or url.fragment:
        raise ValueError("url must be an HTTP(S) page URL without query strings or fragments")
    if url.username or url.password:
        raise ValueError("Do not record credentials in evidence")
    for field in ("steps", "evidence"):
        items = report.get(field)
        if not isinstance(items, list) or not items or not all(
            isinstance(item, str) and item.strip() for item in items
        ):
            raise ValueError(f"{field} must contain actual browser actions or observations")
    state = read_state(root, session)
    current = fingerprint(root)
    state.setdefault("baseline", current)
    state["receipt"] = {**report, "fingerprint": current, "turn_id": state.get("turn_id")}
    state["pending"] = report["status"] != "passed"
    if report["status"] == "passed":
        state["baseline"] = current
    save_state(root, session, state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("status", "require", "record"))
    parser.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.action is None:
        print(json.dumps(handle_event(ROOT, json.load(sys.stdin))))
        return 0
    if not args.session:
        parser.error("pass --session from the hook context, or set CODEX_THREAD_ID")
    if args.action == "record":
        if not args.report:
            parser.error("record requires --report")
        record(ROOT, args.session, json.loads(args.report.read_text()))
    elif args.action == "require":
        state = read_state(ROOT, args.session)
        state.setdefault("baseline", fingerprint(ROOT))
        state.update(pending=True)
        state.pop("receipt", None)
        save_state(ROOT, args.session, state)
    print(json.dumps(read_state(ROOT, args.session), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # A broken gate must be visible, without inventing a successful check.
        print(json.dumps({"systemMessage": f"Browser E2E hook failed: {type(exc).__name__}. "
                          "Follow docs/BROWSER_E2E.md manually; validation is not confirmed."}))
        raise SystemExit(1)
