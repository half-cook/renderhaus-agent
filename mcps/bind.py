"""Register provider callables on a FastMCP stdio server."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP


def bind_tools(mcp: FastMCP, handlers: dict[str, Callable[..., Any]]) -> None:
    for name, fn in handlers.items():
        @functools.wraps(fn)
        def wrapper(*args: Any, bound_fn: Callable[..., Any] = fn, **kwargs: Any) -> Any:
            return bound_fn(*args, **kwargs)

        wrapper.__name__ = name
        wrapper.__qualname__ = name
        mcp.tool(name=name)(wrapper)
