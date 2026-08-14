"""Dispatch Gateway tools and generate AgentCore tool schemas from provider APIs."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from providers.catalog import PROVIDERS, ProviderSpec, get_provider


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SCHEMA_DIR = ROOT / "configs" / "gateway"
LEGACY_MUREKA_SCHEMA_PATH = ROOT / "configs" / "mureka_gateway_tools.json"
FORBIDDEN_TOOL_RE = re.compile(r"^(wait_for_.*|.*_and_wait)$")


def is_forbidden_gateway_tool(name: str) -> bool:
    return bool(FORBIDDEN_TOOL_RE.match(name))


def schema_path(spec: ProviderSpec) -> Path:
    return GATEWAY_SCHEMA_DIR / f"{spec.id}.tools.json"


_STRING_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
}


def _unwrap_optional(hint: Any) -> Any:
    origin = get_origin(hint)
    if origin in {Union, UnionType}:
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


def _json_schema_for_hint(hint: Any) -> dict[str, Any]:
    if isinstance(hint, str):
        stripped = hint.replace(" ", "")
        if stripped.endswith("|None"):
            stripped = stripped[: -len("|None")]
        if stripped.startswith("Literal["):
            return {"type": "string"}
        hint = _STRING_TYPE_MAP.get(stripped, hint)
    hint = _unwrap_optional(hint)
    origin = get_origin(hint)
    args = get_args(hint)
    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": list(values)}
        if values and all(isinstance(value, bool) for value in values):
            schema["type"] = "boolean"
        elif values and all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            schema["type"] = "integer"
        elif values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            schema["type"] = "number"
        else:
            schema["type"] = "string"
        return schema
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }
    json_type = mapping.get(hint)
    if json_type:
        return {"type": json_type}
    return {"type": "string"}


def schema_from_callable(name: str, fn: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001 - fall back to annotations as written
        hints = getattr(fn, "__annotations__", {})
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in signature.parameters.items():
        if param_name in {"self", "cls"} or param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        hint = hints.get(param_name, Any)
        properties[param_name] = _json_schema_for_hint(hint)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    description = inspect.getdoc(fn) or f"{name} provider tool."
    description = description.strip().split("\n", 1)[0]
    schema: dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
        },
    }
    if required:
        schema["inputSchema"]["required"] = required
    else:
        schema["inputSchema"]["required"] = []
    return schema


def gateway_tools(spec: ProviderSpec) -> tuple[str, ...]:
    module = __import__(spec.module_path, fromlist=["GATEWAY_TOOLS", "TOOL_HANDLERS"])
    names = getattr(module, "GATEWAY_TOOLS", None)
    if names is None:
        names = tuple(getattr(module, "TOOL_HANDLERS", {}))
    return tuple(names)


def generate_schemas(spec: ProviderSpec) -> list[dict[str, Any]]:
    module = __import__(spec.module_path, fromlist=["GATEWAY_SCHEMAS", "TOOL_HANDLERS", "GATEWAY_TOOLS"])
    explicit = getattr(module, "GATEWAY_SCHEMAS", None)
    if explicit is not None:
        return list(explicit)
    handlers = getattr(module, "TOOL_HANDLERS")
    tools = []
    for name in gateway_tools(spec):
        if is_forbidden_gateway_tool(name):
            raise ValueError(
                f"{spec.id} Gateway tool {name!r} is a blocking wait helper. "
                "Keep wait_for_* / *_and_wait off Gateway; poll get_* instead."
            )
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"{spec.id} GATEWAY_TOOLS lists {name!r} but TOOL_HANDLERS does not.")
        tools.append(schema_from_callable(name, handler))
    return tools


def write_schemas(spec: ProviderSpec, tools: list[dict[str, Any]] | None = None) -> Path:
    GATEWAY_SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    payload = tools if tools is not None else generate_schemas(spec)
    path = schema_path(spec)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    if spec.id == "mureka":
        LEGACY_MUREKA_SCHEMA_PATH.write_text(path.read_text())
    return path


def load_committed_schemas(spec: ProviderSpec) -> list[dict[str, Any]]:
    path = schema_path(spec)
    if not path.exists():
        raise FileNotFoundError(f"Missing committed Gateway schema: {path}")
    tools = json.loads(path.read_text())
    if not isinstance(tools, list) or not tools:
        raise ValueError(f"{path} must be a non-empty list of tool schemas")
    return tools


def dispatch(provider_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if is_forbidden_gateway_tool(tool_name):
        raise ValueError(
            f"{tool_name} is not a Gateway tool. Blocking wait helpers stay off Lambda; poll get_* instead."
        )
    spec = get_provider(provider_id)
    module = __import__(spec.module_path, fromlist=["TOOL_HANDLERS", "dispatch_tool", "GATEWAY_TOOLS"])
    allowed = set(gateway_tools(spec))
    if tool_name not in allowed:
        raise ValueError(f"Unknown {provider_id} Gateway tool: {tool_name}")
    dispatch_tool = getattr(module, "dispatch_tool", None)
    if callable(dispatch_tool):
        result = dispatch_tool(tool_name, arguments)
    else:
        handler = getattr(module, "TOOL_HANDLERS")[tool_name]
        cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
        result = handler(**cleaned)
    if not isinstance(result, dict):
        return {"result": result}
    return result


def dummy_arguments(schema: dict[str, Any]) -> dict[str, Any]:
    props = (schema.get("inputSchema") or {}).get("properties") or {}
    required = (schema.get("inputSchema") or {}).get("required") or []
    args: dict[str, Any] = {}
    for name in required:
        json_type = (props.get(name) or {}).get("type", "string")
        if json_type == "integer":
            args[name] = 1
        elif json_type == "number":
            args[name] = 1.0
        elif json_type == "boolean":
            args[name] = False
        elif json_type == "array":
            args[name] = []
        elif json_type == "object":
            args[name] = {}
        else:
            args[name] = "ci-smoke"
    return args


def iter_providers() -> tuple[ProviderSpec, ...]:
    return PROVIDERS
