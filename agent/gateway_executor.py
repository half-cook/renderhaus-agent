from __future__ import annotations

import asyncio
import json
import os
import re
import time
from types import SimpleNamespace

from jsonschema import validate, ValidationError as SchemaValidationError
from mcp import Tool

from agent.deep_agent.routing import (
    is_free_tool, premium_video, policy_blocker, estimate_cost, job_type,
    select_provider, intent_constraints, effective_model, tool_parts,
    resolution_value,
)
from agent.deep_agent.outcomes import OutcomeStore

from agent.codex_harness import ToolApprovalPending
from agent.studio_agent_next import (
    _GATEWAY_SEARCH_TOOL,
    _append_harvested_event,
    _asset_version_ids,
    _compact_tool_arguments,
    _progress,
    _record_stream_event,
    _unwrap_tool_output,
)


# Free, non-generative tools that only package existing project media. They
# create no paid provider work, so they never pause for customer approval.
APPROVAL_EXEMPT_TOOLS = frozenset({"Remotion___export_nle_timeline"})
SPENDING_SESSION_TYPE = "renderhaus_run_spending"


def tool_needs_approval(name: str, autonomous: bool) -> bool:
    from providers.elevenlabs.catalog import requires_approval

    if name in APPROVAL_EXEMPT_TOOLS:
        return False
    return not autonomous or requires_approval(name) or premium_video(name)


class GatewayExecutor:
    def __init__(self, studio, servers, session=None, *, run_scope=None):
        self.studio = studio
        self.servers = servers
        self.run_scope = run_scope or studio.job_id
        raw_cap = os.getenv("RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS", "").strip()
        self.cap_cents = int(raw_cap) if raw_cap and studio.autonomous else None
        if self.cap_cents is not None and self.cap_cents < 0:
            raise ValueError("RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS must be nonnegative.")
        if self.cap_cents is not None and not studio.job_id:
            raise ValueError("An autonomous spending cap requires a stable job_id for this run.")
        budget = next((item["spending"] for item in reversed(studio.session_items)
            if item.get("type") == SPENDING_SESSION_TYPE and
            item["spending"].get("scope") == self.run_scope), None) or (session or {}).get("spending") or {}
        self.reservations = dict(budget.get("reservations") or {}) if budget.get("scope") == self.run_scope else {}
        self.cap_stopped = budget.get("stopped", False) if budget.get("scope") == self.run_scope else False
        self.render_jobs = dict((session or {}).get("render_jobs") or {})
        self.media_jobs = dict((session or {}).get("media_jobs") or {})
        self.rejected_reviews = dict((session or {}).get("rejected_reviews") or {})
        self.outcomes = OutcomeStore()
        for event in studio.tool_events:
            self.restore_media_review(self.media_jobs, event)
            if event.name.endswith("render_timeline") and event.result.get("render_id"):
                self.render_jobs.setdefault(event.result["render_id"], dict(event.result))
            if event.name.endswith("get_render_progress") and event.status == "succeeded":
                render_id = event.result.get("render_id") or event.arguments.get("render_id")
                if render_id in self.render_jobs:
                    self.render_jobs[render_id].update(event.result)
        if session:
            studio.source_versions.update(session.get("source_versions") or {})
            studio.add_assets(list((session.get("working_assets") or {}).values()))

    @classmethod
    def restore_media_review(cls, media_jobs, event):
        for job in media_jobs.values():
            if (job.get("provider_job_id") and job["provider_job_id"] == event.provider_job_id
                    and job["provider"] == tool_parts(event.name)[0]):
                job["status"] = event.status
                job["asset"] = cls.review_asset(event, job["provider"], job["model"], job["asset"])

    def publish_spending(self):
        for snapshot in self.studio.session_items:
            if snapshot.get("type") in {"renderhaus_deepagents_session", "renderhaus_codex_session"}:
                snapshot["media_jobs"] = dict(self.media_jobs)
                snapshot["rejected_reviews"] = dict(self.rejected_reviews)
        spending = self.snapshot()["spending"]
        self.studio.session_items = [item for item in self.studio.session_items
                                     if item.get("type") != SPENDING_SESSION_TYPE] + [
            {"type": SPENDING_SESSION_TYPE, "spending": spending},
        ]
        if self.studio.session_sink:
            self.studio.session_sink(self.studio.session_items)

    async def connect_tools(self, session=None):
        for server in self.servers:
            await server.list_tools()
            if session and hasattr(server, "_discovered_tool_names"):
                cached = {tool.name: tool for tool in (server._tools_list or [])}
                for item in session.get("gateway_tools", []):
                    tool = Tool.model_validate(item)
                    cached.setdefault(tool.name, tool)
                    server._discovered_tool_names.add(tool.name)
                server._tools_list = list(cached.values())

    async def available(self):
        return {
            tool.name: (server, tool)
            for server in self.servers for tool in await server.list_tools()
        }

    def snapshot(self):
        return {
            "spending": {"scope": self.run_scope, "reservations": dict(self.reservations),
                         "stopped": self.cap_stopped},
            "source_versions": self.studio.source_versions,
            "working_assets": self.studio.working_assets,
            "render_jobs": self.render_jobs,
            "media_jobs": self.media_jobs,
            "rejected_reviews": self.rejected_reviews,
            "gateway_tools": [
                tool.model_dump(by_alias=True, exclude_none=True)
                for server in self.servers
                for tool in (getattr(server, "_tools_list", None) or [])
                if tool.name != _GATEWAY_SEARCH_TOOL
            ],
        }

    def media_selection(self, name, arguments):
        job = job_type(name)
        if not job or is_free_tool(name):
            return None
        constraints = intent_constraints(self.studio.prompt, tier=self.studio.quality_tier,
                                         confidential=self.studio.confidential)
        rejected_id = self.rejected_reviews.get(job)
        rejected = self.media_jobs.get(rejected_id, {})
        retry = bool(rejected_id and (rejected.get("retry_scope") == self.run_scope or
                     re.search(r"\bretry\b|rejected shot", self.studio.prompt, re.I)))
        if retry:
            for key, value in rejected.get("required", {}).items():
                constraints["required"][key] = max(value, constraints["required"].get(key, 0))
        variant = "image_edit" if name.endswith("image_to_image") else "reference" if name.endswith("reference_to_video") else job
        route = select_provider(job, arguments=arguments, tool_variant=variant, retry=retry, **constraints)
        return route

    def disclose_selection(self, route, event_id):
        if route:
            _progress(self.studio, event_id=f"provider-{event_id}", event_type="MODEL_UPDATE",
                      title="Provider choice", message=route.disclosure or route.reason,
                      status="completed")

    def selection_blocker(self, name, arguments, route):
        provider, tool = tool_parts(name)
        if self.studio.confidential and provider not in {"fal", "remotion"} and not is_free_tool(name):
            return "Confidential projects permit Wan generation only. Reuse existing media for assembly."
        if route is None:
            return None
        if route.status != "ready":
            return route.reason
        if name != route.tool or effective_model(provider, tool, arguments) != route.model:
            return f"Provider ladder selected {route.tool} ({route.model}). Discover its schema and use that route. {route.reason}"
        for field, feature in [("generate_audio", "native_audio"), ("multi_shot", "multi_shot")]:
            if route.required.get(feature) and not arguments.get(field):
                return f"Required capability {feature} must be enabled with {field}=true on the selected route."
        if route.required.get("start_end_frame") and not any(arguments.get(key) for key in (
            "last_frame_url", "end_image_path_or_url", "last_frame_path_or_url",
        )):
            return "Required end frame must be supplied using the selected tool's end-frame field."
        if route.required.get("reference_elements") and not (arguments.get("elements") or arguments.get("ref_image_urls")):
            return "Required reference elements must be supplied using the selected tool's reference field."
        if route.required.get("max_resolution"):
            value = (arguments.get("ratio", "1280:720") if provider == "runway" else
                     arguments.get("size", "2K") if provider == "seedream" else arguments.get("resolution", "720p"))
            actual = resolution_value(value)
            if actual < route.required["max_resolution"]:
                return "Required output resolution must be set in the selected tool's native arguments."
        if route.required.get("duration_seconds"):
            actual = arguments.get("duration_seconds", arguments.get("video_duration_seconds",
                     arguments.get("source_duration_seconds", 5)))
            if provider == "fal":
                fps = arguments.get("frames_per_second", 16)
                actual = (arguments.get("num_frames", 81) - 1) / fps if fps > 0 else 0
            if actual != route.required["duration_seconds"]:
                return "Required duration must be set in the selected tool's native arguments."
        return None

    def record_outcome(self, call_id, outcome):
        """Record an explicit asset review using saved host provenance, never model-supplied flags."""
        job = self.media_jobs.get(call_id)
        if job is None:
            return {"status": "not_run", "reason": "Review requires a saved generation call or provider job."}
        if outcome not in {"accepted", "rejected"}:
            return {"status": "not_run", "reason": "Review outcome must be accepted or rejected."}
        patterns = {"accepted": r"\baccept(?:ed)?\b|\bkeep (?:it|this|the shot)\b|looks good|satisfied with",
                    "rejected": r"\breject(?:ed)?\b|\bredo\b|not right|bad shot"}
        if not re.search(patterns[outcome], self.studio.prompt, re.I) or (
            outcome == "accepted" and re.search(r"do not accept|don't accept|not accepted", self.studio.prompt, re.I)
        ):
            return {"status": "not_run", "reason": "Review requires an explicit customer verdict in the current request."}
        if job["status"] != "succeeded":
            return {"status": "not_run", "reason": "Only a completed artifact can be reviewed; queued and dry-run jobs are incomplete."}
        row = self.outcomes.record(
            event_id=f"review-{call_id}-{outcome}", provider=job["provider"], model=job["model"],
            job_type=job["job_type"], provider_job_id=job.get("provider_job_id"),
            outcome=outcome, stage="review", asset=job["asset"],
            workspace_id=self.studio.workspace_id, project_id=self.studio.project_id,
            execution_id=self.studio.job_id,
        )
        if job.get("review") == outcome:
            return {"status": "recorded", "outcome": row}
        job["review"] = outcome
        if outcome == "rejected":
            job["retry_scope"] = self.run_scope
            self.rejected_reviews[job["job_type"]] = call_id
            self.publish_spending()
            retry = select_provider(job["job_type"], required=job["required"], arguments=job["arguments"],
                                    retry=True, confidential=self.studio.confidential)
            self.disclose_selection(retry, f"retry-{call_id}")
            return {"status": "recorded", "outcome": row, "retry_route": retry.public()}
        self.publish_spending()
        return {"status": "recorded", "outcome": row}

    async def execute(self, call, *, approved=False, rejection=None):
        studio, render_jobs = self.studio, self.render_jobs
        name, arguments, call_id = call["tool_name"], call["arguments"], call["call_id"]
        if name.endswith("___render_timeline"):
            unfinished = [job for job in render_jobs.values()
                          if job.get("status") in {"queued", "running", "preparing"}]
            if unfinished:
                return {"status": "not_run", "reason": "Check the existing render before starting any replacement. A polling error does not mean rendering failed.",
                        "next_tool": "Remotion___get_render_progress",
                        "arguments": {key: unfinished[-1][key] for key in ("render_id", "bucket_name", "output_key") if key in unfinished[-1]}}
            reused = next((event for event in studio.tool_events
                           if event.name == name and event.arguments == arguments
                           and event.result.get("render_id") and event.status not in {"failed", "error"}), None)
            if reused:
                return {**reused.result, "note": "This exact edit already has a render. Check its progress; no duplicate was started."}
        if name.endswith("___get_render_progress"):
            render = render_jobs.get(arguments.get("render_id"))
            if render:
                # These opaque provider identifiers must not be retyped by the
                # model. A one-character bucket change made valid renders look failed.
                arguments = {**arguments, "bucket_name": render["bucket_name"],
                             "output_key": render.get("output_key", "")}
                call = {**call, "arguments": arguments}
            completed_poll = next((event for event in studio.tool_events
                                   if event.name == name and event.status == "succeeded"
                                   and event.arguments.get("render_id") == arguments.get("render_id")), None)
            if completed_poll:
                return {**completed_poll.result, "note": "Already completed and saved in this execution. Deliver this MP4; no additional status check is needed."}
        previous = next(
            (
                event
                for event in studio.tool_events
                if event.id == call_id and event.status not in {"running", "awaiting_approval"}
            ),
            None,
        )
        if previous:
            return previous.result
        registry = await self.available()
        if name not in registry:
            return {"status": "failed", "error": "Search for this Gateway tool before invoking it."}
        server, tool = registry[name]
        try:
            validate(arguments, tool.input_schema)
        except SchemaValidationError as exc:
            return {
                "status": "failed",
                "error": "Arguments do not match the discovered tool schema.",
                "path": list(exc.absolute_path),
            }
        blocker = policy_blocker(name, arguments)
        route = self.media_selection(name, arguments)
        self.disclose_selection(route, call_id)
        blocker = blocker or self.selection_blocker(name, arguments, route)
        if blocker and rejection is None:
            return {"status": "not_run", "reason": blocker, "route": route.public() if route else None}
        if tool_needs_approval(name, studio.autonomous) and not approved and rejection is None:
            raise ToolApprovalPending(call)
        if rejection is not None:
            output = {"status": "rejected", "message": rejection}
        else:
            if self.cap_cents is not None and not is_free_tool(name):
                quote = estimate_cost(name, arguments)
                spent = sum(self.reservations.values())
                if self.cap_stopped or quote.total_cents is None or spent + quote.total_cents > self.cap_cents:
                    already_stopped = self.cap_stopped
                    self.cap_stopped = True
                    self.publish_spending()
                    return {"status": "not_run", "reason": "Autonomous spending cap stopped paid dispatch. "
                            + ("Paid dispatch was already stopped in this run." if already_stopped else
                               quote.description if quote.total_cents is None else
                               f"Estimated spend {spent + quote.total_cents} cents exceeds cap {self.cap_cents} cents."),
                            "spent_cents": spent, "cap_cents": self.cap_cents}
                if call_id in self.reservations:
                    return {"status": "not_run", "reason": "This paid call was already reserved; reconcile its saved job before retrying."}
                self.reservations[call_id] = quote.total_cents
                self.publish_spending()
            if route:
                self.rejected_reviews.pop(route.job_type, None)
            _record_stream_event(
                SimpleNamespace(
                    type="run_item_stream_event",
                    name="tool_called",
                    item=SimpleNamespace(
                        call_id=call_id, tool_name=name, arguments=json.dumps(arguments)
                    ),
                ),
                studio,
                {},
                {},
            )
            try:
                output = await server.call_tool(name, arguments)
                if name.rsplit("___", 1)[-1] in {
                    "query_music_task", "get_music_task", "get_video_task", "get_runway_task",
                    "get_render_progress",
                }:
                    started = time.monotonic()
                    deadline = started + float(os.getenv("STUDIO_MEDIA_WAIT_SECONDS", "600"))
                    while _unwrap_tool_output(output).get("status") in {
                        "preparing", "queued", "running", "streaming", "pending", "processing"
                    }:
                        payload = _unwrap_tool_output(output)
                        elapsed = int(time.monotonic() - started)
                        percent = payload.get("progress")
                        detail = f" · {float(percent):.0%}" if isinstance(percent, (float, int)) else ""
                        _progress(
                            studio, event_id=f"wait-{call_id}", event_type="MEDIA_WAIT",
                            title="Rendering video" if "render_progress" in name else "Waiting for media",
                            message=f"{completed_label(name)}{detail} · {elapsed}s elapsed. Checking automatically.",
                            status="running", tool_call_id=call_id, tool_call_name=name,
                        )
                        if time.monotonic() >= deadline:
                            output = {**payload, "wait_timed_out": True,
                                      "note": "The existing job is still running. Its id is saved; resume to check it without generating again."}
                            break
                        await asyncio.sleep(min(8, max(0, deadline - time.monotonic())))
                        output = await server.call_tool(name, arguments)
                    _progress(
                        studio, event_id=f"wait-{call_id}", event_type="MEDIA_WAIT",
                        title="Media status", message="Status check finished.",
                        status="completed", tool_call_id=call_id, tool_call_name=name,
                    )
            except Exception as exc:
                payload = getattr(exc, "payload", {})
                output = {**payload, "status": "failed", "error": str(exc)[:400],
                          "transport_error": not bool(payload.get("render_id") and payload.get("status") == "failed")}
        saving_media = bool(studio.asset_registrar and _unwrap_tool_output(output).get("status") == "succeeded")
        if saving_media:
            _progress(studio, event_id=f"save-{call_id}", event_type="MEDIA_WAIT", title="Saving media",
                      message="Saving completed media to your project…", status="running")
        source_version_ids = _asset_version_ids(arguments)
        if is_free_tool(name) and arguments.get("job_id"):
            for job in self.media_jobs.values():
                if job.get("provider_job_id") == arguments["job_id"] and job["provider"] == tool_parts(name)[0]:
                    source_version_ids = list(dict.fromkeys(source_version_ids + _asset_version_ids(job["arguments"])))
        await asyncio.to_thread(
            _append_harvested_event,
            studio,
            call_id=call_id,
            name=name,
            arguments=_compact_tool_arguments(arguments),
            output=output,
            source_version_ids=source_version_ids,
        )
        if saving_media:
            _progress(studio, event_id=f"save-{call_id}", event_type="MEDIA_WAIT", title="Media saved",
                      message="Completed media saved to your project.", status="completed")
        completed = next(event for event in studio.tool_events if event.id == call_id)
        if route:
            provider, tool_name = tool_parts(name)
            model = effective_model(provider, tool_name, arguments)
            payload = _unwrap_tool_output(output)
            provider_job_id = completed.provider_job_id or payload.get("job_id")
            self.outcomes.record(
                event_id=f"approval-{self.run_scope}-{call_id}", provider=provider, model=model,
                job_type=job_type(name), provider_job_id=provider_job_id,
                outcome="rejected" if rejection is not None else "accepted", stage="approval",
                workspace_id=studio.workspace_id, project_id=studio.project_id, execution_id=studio.job_id,
            )
            if rejection is None:
                self.media_jobs[call_id] = {
                    "provider": provider, "model": model, "job_type": route.job_type,
                    "provider_job_id": provider_job_id, "status": completed.status,
                    "arguments": arguments, "required": route.required,
                    "asset": self.review_asset(completed, provider, model),
                }
        elif is_free_tool(name) and arguments.get("job_id"):
            for job in self.media_jobs.values():
                if job.get("provider_job_id") == arguments["job_id"] and job["provider"] == tool_parts(name)[0]:
                    job["status"] = completed.status
                    job["asset"] = self.review_asset(completed, job["provider"], job["model"], job["asset"])
        if name.endswith("render_timeline") and completed.result.get("render_id"):
            render_jobs[completed.result["render_id"]] = completed.result
        if name.endswith("get_render_progress") and arguments.get("render_id") in render_jobs:
            result = completed.result
            if result.get("status") == "succeeded" or (result.get("status") == "failed" and not result.get("transport_error")):
                render_jobs[arguments["render_id"]].update(result)
        _progress(
            studio,
            event_id=f"tool-{call_id}",
            event_type="TOOL_CALL_RESULT",
            title=completed.label,
            message=completed.summary,
            status=completed.status,
            tool_call_id=call_id,
            tool_call_name=name,
        )
        if name == _GATEWAY_SEARCH_TOOL:
            return {
                "result": _unwrap_tool_output(output),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                    for _, tool in (await self.available()).values()
                    if tool.name != _GATEWAY_SEARCH_TOOL
                ],
            }
        return completed.result

    @staticmethod
    def review_asset(completed, provider, model, previous=None):
        provenance = {**(previous or {}), **completed.result}
        asset = {key: provenance[key] for key in (
            "weights_license", "training_eligible", "dry_run", "region", "version_id",
        ) if key in provenance}
        owned = completed.assets[0] if len(completed.assets) == 1 else {}
        asset.update(provider=provider, model=model, status=completed.status)
        if owned:
            asset["version_id"] = owned["version_id"]
            asset["training_eligible"] = owned.get("training_eligible") is True and asset.get("training_eligible") is True
        elif not previous or not previous.get("version_id"):
            asset.pop("version_id", None)
            asset["training_eligible"] = False
        if previous and previous.get("version_id") and previous.get("training_eligible") is False:
            asset["training_eligible"] = False
        return asset


def completed_label(name: str) -> str:
    if name.endswith("get_render_progress"):
        return "Remotion is assembling the MP4"
    if name.endswith(("query_music_task", "get_music_task")):
        return "The audio provider is preparing the soundtrack"
    return "The video provider is processing the clip"
