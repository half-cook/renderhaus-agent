#!/usr/bin/env python3
"""Fast CI checks that do not call paid providers."""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _force_dry_run() -> None:
    os.environ["SEEDANCE_DRY_RUN"] = "true"
    os.environ["SEEDREAM_DRY_RUN"] = "true"
    os.environ["MUREKA_DRY_RUN"] = "true"
    os.environ["FISH_AUDIO_DRY_RUN"] = "true"
    os.environ["REMOTION_DRY_RUN"] = "true"


_force_dry_run()


def check_gateway_tools_schema() -> None:
    from providers.catalog import PROVIDERS
    from providers.registry import (
        generate_schemas,
        is_forbidden_gateway_tool,
        load_committed_schemas,
    )

    for spec in PROVIDERS:
        generated = generate_schemas(spec)
        committed = load_committed_schemas(spec)
        assert committed == generated, (
            f"schema drift for {spec.id}: run python scripts/generate_gateway_schemas.py"
        )
        names = [tool["name"] for tool in committed]
        forbidden = [name for name in names if is_forbidden_gateway_tool(name)]
        assert not forbidden, f"{spec.id} Gateway schema includes wait tools: {forbidden}"
        for tool in generated:
            input_schema = tool.get("inputSchema") or {}
            _assert_gateway_shape(input_schema)
            properties = input_schema.get("properties") or {}
            required = input_schema.get("required") or []
            missing = [name for name in required if name not in properties]
            assert not missing, (
                f"{spec.id}.{tool['name']} required fields missing from properties: {missing}"
            )
        print(f"ok {spec.id} gateway schema ({len(names)} tools)")


def _assert_gateway_shape(schema: object) -> None:
    if not isinstance(schema, dict):
        return
    extra = set(schema) - {"type", "properties", "required", "items", "description"}
    assert not extra, f"Gateway schema has unsupported keys: {sorted(extra)}"
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            _assert_gateway_shape(child)
    _assert_gateway_shape(schema.get("items"))


def check_dry_run_dispatch() -> None:
    _force_dry_run()
    from providers.catalog import PROVIDERS
    from providers.registry import dispatch, dummy_arguments, load_committed_schemas

    for spec in PROVIDERS:
        for schema in load_committed_schemas(spec):
            name = schema["name"]
            result = dispatch(spec.id, name, dummy_arguments(schema))
            assert isinstance(result, dict), f"{spec.id}.{name} did not return a dict"
            if "error" in result and result.get("error_type"):
                raise AssertionError(f"{spec.id}.{name} dispatch error: {result}")
            print(f"ok dry-run {spec.id}.{name} status={result.get('status', 'ok')}")


def check_imports() -> None:
    from lambdas import handler as generic_handler
    from lambdas.mureka import handler as mureka_handler
    from providers.mureka import api as mureka_api
    from server import app, config  # noqa: F401

    assert callable(generic_handler.handler)
    assert callable(mureka_handler.handler)
    assert isinstance(mureka_api.dry_run(), bool)
    print("ok python imports")


def check_lambda_zip() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "deploy_gateway", ROOT / "scripts" / "deploy_gateway.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scripts/deploy_gateway.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    zip_bytes = module.build_lambda_zip()
    assert zip_bytes[:2] == b"PK", "lambda zip is not a zip archive"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
    linux_native = [
        name
        for name in names
        if "pydantic_core" in name and name.endswith(".so") and "linux" in name
    ]
    assert linux_native, (
        "lambda zip is missing a Linux pydantic_core native module; "
        "pip-install with --platform manylinux2014_aarch64 --python-version 3.11"
    )
    print(f"ok lambda zip ({len(zip_bytes)} bytes)")


def main() -> int:
    check_gateway_tools_schema()
    check_imports()
    check_dry_run_dispatch()
    check_lambda_zip()
    print("ci_check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ci_check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
