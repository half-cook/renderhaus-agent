from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def langfuse_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def get_langfuse():
    """Return the Langfuse client. Call only after load_local_env()."""
    from langfuse import get_client

    return get_client()


def langchain_callbacks() -> list[Any]:
    if not langfuse_configured():
        return []
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]


def flush_langfuse() -> None:
    if not langfuse_configured():
        return
    get_langfuse().flush()


@contextmanager
def traced_operation(
    name: str,
    *,
    as_type: str = "span",
    input: Any | None = None,
    session_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    trace_name: str | None = None,
) -> Iterator[Any | None]:
    """Wrap work in a Langfuse observation; no-op when credentials are missing."""
    if not langfuse_configured():
        yield None
        return

    from langfuse import propagate_attributes

    langfuse = get_langfuse()
    with langfuse.start_as_current_observation(
        name=name,
        as_type=as_type,  # type: ignore[arg-type]
        input=input,
        metadata=metadata,
    ) as observation:
        attr_kwargs: dict[str, Any] = {}
        if session_id:
            attr_kwargs["session_id"] = session_id
        if tags:
            attr_kwargs["tags"] = tags
        if metadata:
            attr_kwargs["metadata"] = {k: str(v) for k, v in metadata.items()}
        if trace_name:
            attr_kwargs["trace_name"] = trace_name
        if attr_kwargs:
            with propagate_attributes(**attr_kwargs):
                yield observation
        else:
            yield observation
