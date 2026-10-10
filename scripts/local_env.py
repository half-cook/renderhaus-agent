#!/usr/bin/env python3
"""Run local services using the caller's AWS identity. Never serialize credentials."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import boto3
from botocore.exceptions import ClientError

from server.config import load_local_env
from server.local_profile import capture_local_profile, dry_run_table, studio_environment
from server.secrets import aws_region, fetch_secret_map, secrets_locator


SERVICES = {
    "gateway": ("127.0.0.1", 8765),
    "backend": ("127.0.0.1", 8000),
    "studio": ("localhost", 5174),
}
AWS_ACTIONS = {
    "NoCredentialsError": "Run aws configure --profile {profile}, or configure SSO and log in.",
    "PartialCredentialsError": "Complete your AWS profile or unset incomplete shell access keys.",
    "ProfileNotFound": "Check AWS_PROFILE and configure that profile with aws configure.",
    "ExpiredToken": "Run aws sso login --profile {profile}, or refresh temporary access keys.",
    "ExpiredTokenException": "Run aws sso login --profile {profile}, or refresh temporary access keys.",
    "SSOUnauthorizedTokenError": "Run aws sso login --profile {profile}.",
    "TokenRetrievalError": "Run aws sso login --profile {profile}.",
    "UnauthorizedSSOTokenError": "Run aws sso login --profile {profile}.",
    "InvalidClientTokenId": "Check your AWS_PROFILE or refresh shell access keys.",
    "UnrecognizedClientException": "Check your AWS_PROFILE or refresh shell access keys.",
    "AccessDenied": "Ask for the read-only policy in docs/LOCAL_RUN.md.",
    "AccessDeniedException": "Ask for the read-only policy in docs/LOCAL_RUN.md.",
    "ResourceNotFoundException": "Check AWS_REGION and RENDERHAUS_SECRETS_NAME against docs/LOCAL_RUN.md.",
    "EndpointConnectionError": "Check AWS_REGION, your network, and AWS endpoint connectivity.",
    "ConnectTimeoutError": "Check your network and AWS endpoint connectivity.",
    "ReadTimeoutError": "Check your network and retry the read.",
    "DecryptionFailure": "Ask the secret owner to check encryption settings. See docs/LOCAL_RUN.md.",
}


class LocalRunError(Exception):
    def __init__(self, code: str, action: str):
        super().__init__(code)
        self.code = code
        self.action = action


def error_message(error: Exception) -> str:
    if isinstance(error, LocalRunError):
        return f"{error.code}: {error.action}"
    code = (
        error.response.get("Error", {}).get("Code")
        if isinstance(error, ClientError)
        else type(error).__name__
    )
    if code not in AWS_ACTIONS:
        code = (
            "InvalidConfiguration"
            if isinstance(error, (ValueError, KeyError))
            else "LocalRunFailed"
        )
    action = AWS_ACTIONS.get(
        code, "Check local configuration and dependencies in docs/LOCAL_RUN.md."
    )
    return f"{code}: " + action.format(profile='"${AWS_PROFILE:-default}"')


def check_requirements() -> None:
    if sys.version_info < (3, 11):
        raise LocalRunError(
            "PythonVersion",
            "Python >=3.11 is required by pyproject.toml. Run make setup with that Python.",
        )
    node = shutil.which("node")
    if not node or not shutil.which("npm"):
        raise LocalRunError("MissingNode", "Install Node >=20.9.0 and npm. See docs/LOCAL_RUN.md.")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)\s*", version.stdout)
    if version.returncode or not match or tuple(map(int, match.groups())) < (20, 9, 0):
        raise LocalRunError(
            "NodeVersion", "Node >=20.9.0 is required by the locked Clerk dependencies."
        )
    if not (ROOT / "studio/node_modules/next").is_dir():
        raise LocalRunError("MissingNodeModules", "Run npm ci inside studio/.")
    if (ROOT / ".env.local").exists():
        raise LocalRunError(
            "LocalEnvFile",
            "Move root .env.local out of the checkout and use shell bootstrap variables. See docs/LOCAL_RUN.md.",
        )
    # Next automatically reads these files even with a clean child environment.
    if any(
        (ROOT / "studio" / name).exists()
        for name in (".env", ".env.local", ".env.development", ".env.development.local")
    ):
        raise LocalRunError(
            "StudioEnvFile",
            "Move studio/.env* configuration files out of the checkout before using this launcher. It supplies Clerk configuration in memory.",
        )


def check_identity() -> None:
    aws = shutil.which("aws")
    if aws:
        result = subprocess.run(
            [aws, "sts", "get-caller-identity", "--region", aws_region()],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "AWS_PAGER": ""},
        )
        if result.returncode:
            code = next(
                (code for code in AWS_ACTIONS if code in result.stderr), "AWSIdentityFailed"
            )
            if code == "AWSIdentityFailed":
                phrases = {
                    "unable to locate credentials": "NoCredentialsError",
                    "config profile": "ProfileNotFound",
                    "sso token": "SSOUnauthorizedTokenError",
                    "sso session": "SSOUnauthorizedTokenError",
                    "could not connect to the endpoint": "EndpointConnectionError",
                }
                code = next(
                    (code for phrase, code in phrases.items() if phrase in result.stderr.lower()),
                    code,
                )
            if code in AWS_ACTIONS:
                raise ClientError({"Error": {"Code": code}}, "GetCallerIdentity")
            raise LocalRunError(
                code,
                "Check AWS_PROFILE. For SSO, run aws sso login --profile PROFILE. See docs/LOCAL_RUN.md.",
            )
    else:
        boto3.client("sts", region_name=aws_region()).get_caller_identity()


def load_environment() -> list[str]:
    os.environ["RENDERHAUS_LOCAL_PROFILE"] = "local"
    capture_local_profile(os.environ)
    os.environ.setdefault("AWS_REGION", os.getenv("AWS_DEFAULT_REGION") or "us-east-1")
    os.environ.setdefault("RENDERHAUS_SECRETS_NAME", "renderhaus/app")
    locator = secrets_locator()
    if not locator:
        raise LocalRunError("MissingSecretName", "Set RENDERHAUS_SECRETS_NAME=renderhaus/app.")
    values = fetch_secret_map(locator)
    if any(
        not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or "\0" in value for key, value in values.items()
    ):
        raise LocalRunError(
            "InvalidSecret",
            "Secret keys must be environment variable names with string values. Ask the secret owner.",
        )
    load_local_env()
    for key in ("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_SECRET_KEY"):
        if not os.getenv(key):
            raise LocalRunError(
                "MissingClerkConfig",
                "Ask the secret owner to configure both Clerk keys. See docs/LOCAL_RUN.md.",
            )
    return sorted(values)


def report_environment(keys: list[str]) -> None:
    print("AWS identity verified; secret readable. Loaded key names:")
    for key in keys:
        print(f"  {key}")
    print("Effective local dry-run flags:")
    for key, dry in dry_run_table(os.environ).items():
        print(f"  {key} -> {str(dry).lower()}")
    print(
        "Gateway http://127.0.0.1:8765/mcp; backend http://localhost:8000; Studio http://localhost:5174"
    )
    print(
        "Agent LLM calls and Clerk authentication remain live-capable. Media dry-runs produce no final artifacts."
    )


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def check_ports(names: tuple[str, ...]) -> None:
    for name in names:
        if port_open(*SERVICES[name]):
            raise LocalRunError(
                "PortInUse",
                f"The {name} port {SERVICES[name][1]} is already in use. Stop the existing process before starting another.",
            )


def run_service(name: str) -> int:
    check_ports((name,))
    if name == "studio":
        os.chdir(ROOT / "studio")
        npm = shutil.which("npm")
        os.execve(npm, [npm, "run", "dev"], studio_environment(os.environ))
    module = "server.app" if name == "backend" else "scripts.local_gateway"
    sys.argv = [module]
    runpy.run_module(module, run_name="__main__")
    return 0


def process_group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        for child in children:
            child.poll()
        if not any(process_group_alive(child.pid) for child in children):
            break
        time.sleep(0.1)
    for child in children:
        if process_group_alive(child.pid):
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child.wait()


def run_all(shell_env: dict[str, str]) -> int:
    check_ports(tuple(SERVICES))
    log_dir = ROOT / ".renderhaus/logs"
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    children = []
    interrupted = False

    def interrupt(_signum, _frame):
        nonlocal interrupted
        interrupted = True

    old_handlers = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for name in SERVICES:
            if interrupted:
                return 130
            path = log_dir / f"{name}.log"
            with path.open("a") as log:
                path.chmod(0o600)
                child = subprocess.Popen(
                    [sys.executable, str(ROOT / "scripts/local_env.py"), name],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=shell_env,
                    start_new_session=True,
                )
            children.append(child)
            deadline = time.monotonic() + 60
            while not port_open(*SERVICES[name]):
                if interrupted:
                    return 130
                if any(process.poll() is not None for process in children):
                    raise LocalRunError(
                        "ServiceExited",
                        "A local service exited. Read its log in .renderhaus/logs/ locally.",
                    )
                if time.monotonic() >= deadline:
                    raise LocalRunError(
                        "StartupTimeout",
                        f"The {name} port did not open within 60 seconds. Read .renderhaus/logs/{name}.log locally.",
                    )
                time.sleep(0.2)
            print(f"{name} listening on port {SERVICES[name][1]}", flush=True)
        print(
            "Local services started. Logs in .renderhaus/logs/. Ctrl-C stops all children.",
            flush=True,
        )
        while not interrupted:
            if any(child.poll() is not None for child in children):
                raise LocalRunError(
                    "ServiceExited", "A local service exited. Read its log in .renderhaus/logs/."
                )
            time.sleep(0.3)
        return 130
    finally:
        stop_children(children)
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check", "backend", "gateway", "studio", "all", "up", "status"),
        nargs="?",
        default="up",
    )
    parser.add_argument(
        "--print-keys",
        action="store_true",
        help="Report key names and dry-run flags only; do not start services.",
    )
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    shell_env = dict(os.environ)
    # SDK debug logs can contain GetSecretValue responses.
    for name in ("boto3", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        if args.command == "status":
            for name, address in SERVICES.items():
                print(
                    f"{name} port {address[1]}: {'listening' if port_open(*address) else 'closed'}"
                )
            print("Port status does not verify authentication or application health.")
            return 0
        check_requirements()
        os.environ["RENDERHAUS_LOCAL_PROFILE"] = "local"
        capture_local_profile(os.environ)
        check_identity()
        keys = load_environment()
        if args.command == "check" or args.print_keys:
            report_environment(keys)
            return 0
        return run_all(shell_env) if args.command in {"up", "all"} else run_service(args.command)
    except Exception as error:
        print(error_message(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
