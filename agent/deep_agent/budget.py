"""Preflight accounting attached to the concrete model, including SDK-internal calls."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
from typing import Any, Callable, TypeVar
import uuid

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from agent.deep_agent.usage import MODEL_RATES, ModelRates, ModelUsage
from server import run_budget as rb


@dataclass(frozen=True)
class ModelEnvelope:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    input_basis: str

    @property
    def cents(self) -> int:
        return rb.orchestration_total_cents(self.cost_usd) if rb.orchestration_billing_enabled() else 0


_REQUEST_FIELDS = frozenset({
    "tools", "tool_choice", "max_tokens", "thinking", "output_config", "response_format", "cache_control",
    "system", "mcp_servers", "container", "betas", "service_tier", "inference_geo", "speed",
})
_TEXT_BLOCKS = frozenset({"text", "text_delta", "thinking", "redacted_thinking", "tool_use", "tool_result", "function"})


def _image_bound(value: Any) -> tuple[Any, int]:
    if isinstance(value, dict):
        if value.get('type') in {'image', 'image_url'}:
            return {'type': 'text', 'text': '[bounded image]'}, 1
        result, count = {}, 0
        for key, item in value.items():
            result[key], images = _image_bound(item)
            count += images
        return result, count
    if isinstance(value, list):
        result, count = [], 0
        for item in value:
            replacement, images = _image_bound(item)
            result.append(replacement)
            count += images
        return result, count
    return value, 0


def _has_media(value: Any) -> bool:
    if isinstance(value, dict):
        if isinstance(value.get("type"), str) and value["type"] not in _TEXT_BLOCKS:
            return True
        # cache_control ({"type": "ephemeral"}) is prompt-caching metadata, not a media block.
        return any(_has_media(item) for key, item in value.items() if key != "cache_control")
    if isinstance(value, list):
        return any(_has_media(item) for item in value)
    return False


def model_envelope(model: Any, messages: list[list[Any]], invocation_params: dict[str, Any]) -> ModelEnvelope:
    """One token per serialized UTF-8 byte plus protocol overhead; media uses the context ceiling.

    Output includes hidden thinking. Cache writes use the highest supported TTL rate.
    The 4096-token protocol allowance, 1024 tokens per message and documented
    286-token overhead per tool overestimate normal text requests.
    """
    model_name = str(invocation_params.get("model") or invocation_params.get("model_name")
                     or getattr(model, "model", None) or getattr(model, "model_name", "unknown"))
    rates = MODEL_RATES.get(model_name)
    if rates is None:
        raise rb.RunBudgetError("This model has no known price; the call was not started.")
    params = {key: value for key, value in invocation_params.items() if key in _REQUEST_FIELDS}
    extra = getattr(model, "model_kwargs", {}) or {}
    params = {**{key: value for key, value in extra.items() if key in _REQUEST_FIELDS}, **params}
    output_candidates = [params.get("max_tokens"), extra.get("max_tokens"), getattr(model, "max_tokens", None)]
    output = max((value for value in output_candidates if type(value) is int), default=0)
    if output <= 0:
        raise rb.RunBudgetError("This model needs an explicit output-token limit before work starts.")
    if any(params.get(key) or getattr(model, key, None) for key in ("mcp_servers", "container", "speed", "inference_geo")):
        raise rb.RunBudgetError("This request has unpriced model features; the call was not started.")
    if params.get("service_tier") not in {None, "auto", "standard"}:
        raise rb.RunBudgetError("This request has an unpriced service tier; the call was not started.")
    if any(tool.get("type") not in {None, "function", "custom"} for tool in params.get("tools", []) if isinstance(tool, dict)):
        raise rb.RunBudgetError("This request has unpriced model tools; the call was not started.")
    profile = getattr(model, "profile", None) or {}
    context_limit = profile.get("max_input_tokens")
    if len(messages) != 1:
        raise rb.RunBudgetError("Each model call needs its own budget reservation.")
    serialized = [message.model_dump(mode="json") for message in messages[0]]
    bounded_content, image_count = _image_bound([message.content for message in messages[0]])
    if _has_media(bounded_content):
        if type(context_limit) is not int or context_limit <= 0:
            raise rb.RunBudgetError("Media input has no known token ceiling; the call was not started.")
        input_tokens, basis = context_limit, "multimodal_context_ceiling"
    else:
        if hasattr(model, "_get_request_payload"):
            # Pinned langchain-anthropic's payload builder performs no network I/O.
            payload = model._get_request_payload(messages[0], **{**params, "max_tokens": output})
        else:
            payload = {"messages": serialized, **params}
        payload, _ = _image_bound(payload)
        byte_count = len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        # Official vision limit is 4784 visual tokens per image on Claude 4.7+.
        # https://platform.claude.com/docs/en/build-with-claude/vision (2026-10-15).
        input_tokens = byte_count + 4096 + 1024 * len(serialized) + 286 * len(params.get("tools", [])) + image_count * (4784 + 1024)
        if type(context_limit) is int and context_limit > 0:
            input_tokens = min(input_tokens, context_limit)
        basis = "serialized_utf8_bytes_plus_protocol_allowance" + ('_and_bounded_images' if image_count else '')
    if model_name == "claude-haiku-5-5" and input_tokens > 100_000:
        rates = ModelRates(0.50, 2.50, 0.625, 1.0, 0.05)
    input_rate = max(rates.input, rates.cache_write_5m, rates.cache_write_1h, rates.cache_read)
    cost_usd = (input_tokens * input_rate + output * rates.output) / 1_000_000
    return ModelEnvelope(model_name, input_tokens, output, cost_usd, basis)


class ModelBudgetGuard(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, model: Any, meter: Any, role: str) -> None:
        self.model = model
        self.meter = meter
        self.role = role
        self.active: dict[str, ModelEnvelope] = {}

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: uuid.UUID, **kwargs: Any) -> None:
        envelope = model_envelope(self.model, messages, kwargs.get("invocation_params") or {})
        work_id = str(run_id)
        self.meter.reserve_work(work_id, envelope.cents, kind="model", role=self.role, allow_existing=False)
        self.active[work_id] = envelope

    def on_llm_end(self, response: Any, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        work_id = str(run_id)
        envelope = self.active.get(work_id)
        if envelope is None:
            return
        try:
            usage = ModelUsage(work_id)
            total_cost = 0.0
            calls = 0
            for generations in response.generations:
                for generation in generations:
                    message = generation.message
                    metadata = dict(message.response_metadata)
                    returned_model = metadata.get("model_name") or metadata.get("model") or envelope.model
                    if returned_model != envelope.model:
                        raise rb.RunBudgetError("Model usage has a different price; billing needs reconciliation.")
                    metadata["model_name"] = returned_model
                    cost = usage.record(AIMessage(content="", usage_metadata=message.usage_metadata, response_metadata=metadata))
                    if cost is None or not math.isfinite(cost):
                        raise rb.RunBudgetError("Model usage is missing; billing needs reconciliation.")
                    total_cost += cost
                    calls += 1
            if not calls or total_cost > envelope.cost_usd + 1e-12:
                raise rb.RunBudgetError("Model usage exceeds the reserved envelope; billing needs reconciliation.")
            self.meter.settle_work(work_id, model_cost_usd=total_cost, usage={
                "model": envelope.model, "input_tokens_bound": envelope.input_tokens,
                "output_tokens_bound": envelope.output_tokens, "input_basis": envelope.input_basis,
                "records": usage.records(),
            })
        except BaseException:
            self.meter.fail_work(work_id)
            raise
        finally:
            self.active.pop(work_id, None)

    def on_llm_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any) -> None:
        if self.active.pop(str(run_id), None) is not None:
            self.meter.fail_work(str(run_id))


def guard_model(model: Any, meter: Any, *, role: str) -> Any:
    """Clone model callbacks without wrapping its profile, tool binding, or streaming protocol."""
    if meter is None:
        return model
    if not hasattr(model, "max_retries"):
        raise rb.RunBudgetError("This model cannot disable unreserved SDK retries.")
    callbacks = model.callbacks
    updates = {"max_retries": 0, "cache": False}
    if hasattr(model, "stream_usage"):
        updates["stream_usage"] = True
    if callbacks is None or isinstance(callbacks, list):
        callbacks = [callback for callback in callbacks or [] if not isinstance(callback, ModelBudgetGuard)]
        guarded = model.model_copy(update={"callbacks": callbacks, **updates})
        callbacks.append(ModelBudgetGuard(guarded, meter, role))
    else:
        callbacks = callbacks.copy()
        for callback in list(callbacks.handlers):
            if isinstance(callback, ModelBudgetGuard):
                callbacks.remove_handler(callback)
        guarded = model.model_copy(update={"callbacks": callbacks, **updates})
        callbacks.add_handler(ModelBudgetGuard(guarded, meter, role))
    # Anthropic SDK clients are cached properties. A shallow model clone must rebuild
    # them or a previously warmed client would retain its original retry count.
    for key in ("_client_params", "_client", "_async_client"):
        guarded.__dict__.pop(key, None)
    return guarded


class BudgetContextMiddleware(AgentMiddleware):
    def __init__(self, meter: Any) -> None:
        self.meter = meter

    def before_model(self, state: Any, runtime: Any) -> dict:
        snapshot = self.meter.snapshot()
        text = ("Run budget snapshot. " + "; ".join(f"{key}={value}" for key, value in snapshot.items())
                + ". Amounts are integer cents. Reservations include concurrent and unresolved work. "
                  "Choose the smallest useful next step that fits. If the next useful step cannot fit, "
                  "pause for a cap increase before starting work. Never infer unknown prices or retry rejected work.")
        return {'messages': [HumanMessage(content=text, name='host_budget')]}

    async def abefore_model(self, state: Any, runtime: Any) -> dict:
        return self.before_model(state, runtime)


T = TypeVar("T")


def record_local_work(meter: Any, operation: str, action: Callable[[], T], *, max_seconds: float) -> T:
    """Meter local work with a caller-enforced timeout and an optional configured compute rate."""
    if meter is None:
        return action()
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("Local work needs a finite positive execution-time bound.")
    work_id = uuid.uuid4().hex
    rate = rb.local_compute_usd_per_second()
    reserve = rb.orchestration_total_cents(rate * max_seconds) if rb.orchestration_billing_enabled() else 0
    meter.reserve_work(work_id, reserve, kind="local", role=operation)
    started = time.monotonic()
    try:
        return action()
    finally:
        seconds = time.monotonic() - started
        usage = {"actions": 1, "wall_seconds": seconds, "max_seconds": max_seconds,
                 "compute_usd_per_second": rate, "compute_basis": "configured_estimate" if rate else "unpriced_usage_units_only"}
        if seconds > max_seconds:
            meter.fail_work(work_id, usage=usage)
        else:
            meter.settle_work(work_id, compute_cost_usd=seconds * rate, usage=usage)
