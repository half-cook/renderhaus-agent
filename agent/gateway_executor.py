from __future__ import annotations

import asyncio
import json
import logging
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
    tool_variant,
    POLICY,
    request_tool_blocker,
    capability_constraints,
)
from agent.deep_agent.outcomes import OutcomeStore
from agent.hyperframes import HYPERFRAMES_TOOL

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
logger = logging.getLogger("renderhaus.gateway_executor")


def tool_needs_approval(name: str, autonomous: bool) -> bool:
    from providers.elevenlabs.catalog import requires_approval

    if name in APPROVAL_EXEMPT_TOOLS:
        return False
    if name in {"Remotion___prepare_conversational_edit", "Sync___lipsync_video", "sync3_lipsync",
                "HeyGen___create_avatar_video", "heygen_avatar_v"}:
        return True
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
            if cls.matches_media_job(job, event.name, event.provider_job_id):
                job["status"] = event.status
                job["asset"] = cls.review_asset(event, job["provider"], job["model"], job["asset"])

    @staticmethod
    def matches_media_job(job, name, job_id):
        if not job_id or job.get("provider_job_id") != job_id:
            return False
        provider = tool_parts(name)[0]
        if job["provider"] == provider:
            return True
        endpoint, separator, request_id = str(job_id).partition(":")
        return bool(provider == "fal" and job["provider"] == "seedance"
                    and separator and request_id and endpoint.startswith("bytedance/seedance-2.5/")
                    and job.get("endpoint_id") == endpoint and job.get("model") == endpoint)

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
                    if tool.name == HYPERFRAMES_TOOL.name:
                        continue
                    cached.setdefault(tool.name, tool)
                    server._discovered_tool_names.add(tool.name)
                server._tools_list = list(cached.values())

    async def available(self):
        return {
            tool.name: (server, tool)
            for server in self.servers for tool in await server.list_tools()
            if request_tool_blocker(self.studio.prompt, tool.name) is None
        }

    def filter_discovery(self, value):
        if isinstance(value, list):
            filtered = [self.filter_discovery(item) for item in value]
            return [item for item in filtered if item is not None]
        if isinstance(value, dict):
            name = value.get("name") or value.get("toolName") or value.get("tool_name")
            if isinstance(name, str) and request_tool_blocker(self.studio.prompt, name):
                return None
            filtered = {key: self.filter_discovery(item) for key, item in value.items()}
            return {key: item for key, item in filtered.items() if item is not None}
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except ValueError:
                return value
            if isinstance(decoded, (list, dict)):
                return json.dumps(self.filter_discovery(decoded))
        return value

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
                if tool.name not in {_GATEWAY_SEARCH_TOOL, HYPERFRAMES_TOOL.name}
                and request_tool_blocker(self.studio.prompt, tool.name) is None
            ],
        }

    def media_selection(self, name, arguments):
        job = job_type(name)
        if not job or is_free_tool(name):
            return None
        selection_arguments = dict(arguments)
        version_ids = _asset_version_ids(arguments)
        values = list(arguments.values())
        while values:
            value = values.pop()
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, list):
                values.extend(value)
            elif isinstance(value, str) and value in self.studio.source_versions:
                version_ids.append(self.studio.source_versions[value])
        for version_id in version_ids:
            asset = self.studio.working_assets.get(version_id, {})
            metadata = asset.get("metadata", {})
            if (asset.get("real_face_refs") or asset.get("user_supplied_real_person_refs")
                    or isinstance(metadata, dict) and (metadata.get("real_face_refs") or metadata.get("user_supplied_real_person_refs"))):
                selection_arguments["real_face_refs"] = True
        constraints = intent_constraints(self.studio.prompt, confidential=self.studio.confidential,
                                         arguments=selection_arguments)
        if job in {"motion_graphics", "nle_handoff"}:
            constraints["provider"] = constraints["model"] = constraints["named_model"] = None
        rejected_id = self.rejected_reviews.get(job)
        rejected = self.media_jobs.get(rejected_id, {})
        retry = bool(rejected_id and (rejected.get("retry_scope") == self.run_scope or
                     re.search(r"\bretry\b|rejected shot", self.studio.prompt, re.I)))
        if retry:
            for key, value in rejected.get("required", {}).items():
                constraints["required"][key] = max(value, constraints["required"].get(key, 0))
        constraints = capability_constraints(constraints, job)
        variant = tool_variant(name)
        route = select_provider(job, arguments=selection_arguments, tool_variant=variant, retry=retry, **constraints)
        return route

    def dispatch_disclosure(self, name, arguments, route):
        if name == "HeyGen___create_avatar_video":
            consent = "confirmed with a recorded acknowledgement" if arguments.get("consent_confirmed") is True else "required"
            return (f"Provider HeyGen direct; model {effective_model('heygen', 'create_avatar_video', arguments)}. "
                    f"{route.basis if route else 'exception for long presenters'}. {estimate_cost(name, arguments).description} "
                    f"Faces and voices: {arguments.get('subjects') or 'identify every subject'}. Consent {consent}. "
                    "API billing is separate from HeyGen app plans. Non-enterprise uploads may train HeyGen models "
                    "unless the account has opted out; Enterprise data is excluded under vendor terms. "
                    "Outputs are not training eligible. Script duration is an estimate, not a render-length control.")
        if name == "Sync___lipsync_video":
            from providers.sync.contracts import configured_transport

            consent = "confirmed" if arguments.get("consent_confirmed") is True else "required"
            terms = ("Direct Sync terms permit upload reuse for service improvement. "
                     if configured_transport() == "direct" else
                     "fal API terms restrict training on client content except excluded models. ")
            return (f"Provider sync via {configured_transport()}; model {effective_model('sync', 'lipsync_video', arguments)}. "
                    f"{route.basis if route else 'default'}. {estimate_cost(name, arguments).description} "
                    f"Faces and voices: {arguments.get('subjects') or 'identify every subject'}. Consent {consent}. "
                    f"Uploads are processed by the host and Sync. {terms}"
                    "Outputs are not training eligible.")
        if route:
            return route.disclosure or route.reason
        provider, tool = tool_parts(name)
        model = effective_model(provider, tool, arguments) or tool
        proposal = arguments.get("plan_summary", "") if name == "Remotion___prepare_conversational_edit" else ""
        return f"{proposal} Provider {provider}; model {model}; default. {estimate_cost(name, arguments).description}".strip()

    def disclose_selection(self, route, event_id, name=None, arguments=None):
        if route or (name and not is_free_tool(name)):
            message = self.dispatch_disclosure(name, arguments or {}, route)
            _progress(self.studio, event_id=f"provider-{event_id}", event_type="MODEL_UPDATE",
                      title="Provider choice", message=message, status="completed")

    def selection_blocker(self, name, arguments, route):
        if blocker := request_tool_blocker(self.studio.prompt, name):
            return blocker
        provider, tool = tool_parts(name)
        sync_request = None
        if name == "HeyGen___create_avatar_video":
            from providers.heygen.contracts import request_for

            try:
                request_for(arguments)
            except ValueError as exc:
                return str(exc)
        if name == "Sync___lipsync_video" and (
            arguments.get("consent_confirmed") is not True
            or not isinstance(arguments.get("subjects"), str)
            or not arguments["subjects"].strip()
        ):
            return "Lip-sync requires identifying every face/voice subject and explicit consent_confirmed=true."
        if name == "Sync___lipsync_video":
            from providers.sync.contracts import request_for

            try:
                sync_request = request_for(arguments)
            except ValueError as exc:
                return str(exc)
        if route is None:
            return None
        if route.status != "ready":
            return route.reason
        if name != route.tool or effective_model(provider, tool, arguments) != route.model:
            return f"Capability map selected {route.tool} ({route.model}). Discover its schema and use that route. {route.reason}"
        row = next((row for row in POLICY["capabilities"]
                    if row["model"] == route.model and name in row["tools"].values()), {})
        if provider not in {"sync", "heygen"} and route.required.get("real_face_refs") and arguments.get("likeness_consent") is not True:
            return "Real-person likeness references require explicit likeness_consent=true acknowledgement."
        audio_field = row.get("native_audio_field", "generate_audio")
        for field, feature in [(audio_field, "native_audio"), (row.get("multi_shot_field", "multi_shot"), "multi_shot")]:
            if field is None:
                continue
            default = row.get("native_audio_default", False) if feature == "native_audio" else False
            if route.required.get(feature) and not arguments.get(field, default):
                return f"Required capability {feature} must be enabled with {field}=true on the selected route."
        if route.required.get("start_end_frame") and not any(arguments.get(key) for key in (
            "last_frame_url", "end_image_url", "end_image_path_or_url", "last_frame_path_or_url",
        )):
            return "Required end frame must be supplied using the selected tool's end-frame field."
        if route.required.get("reference_elements") and not any(arguments.get(key) for key in (
            "elements", "ref_image_urls", "reference_image_urls", "reference_video_urls",
        )):
            return "Required reference elements must be supplied using the selected tool's reference field."
        if route.required.get("voice_references") and not arguments.get("reference_audio_urls"):
            return "Required voice references must be supplied using reference_audio_urls."
        if route.required.get("max_resolution"):
            if sync_request:
                from providers.sync.chunks import plan_for

                actual = min(sync_request.source_width or 0, sync_request.source_height or 0)
                if len(plan_for(sync_request)) > 1:
                    actual = min(actual, 720)
                if actual < route.required["max_resolution"]:
                    return "Sync inherits source resolution: supply measured source_width/source_height. Chunked output is limited to 720p."
            else:
                value = (arguments.get("ratio", "1280:720") if provider == "runway" else
                         arguments.get("size", "2K") if provider in {"seedream", "openai_images"} else arguments.get("resolution", row.get("resolution_default", "720p")))
                actual = resolution_value(value)
            if actual < route.required["max_resolution"]:
                return "Required output resolution must be set in the selected tool's native arguments."
        if route.required.get("duration_seconds"):
            actual = (sync_request.output_duration if sync_request else
                      arguments.get("duration", arguments.get("duration_seconds", arguments.get("video_duration_seconds",
                      arguments.get("source_duration_seconds", 5)))))
            if provider == "fal" and not row.get("duration_field"):
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
            execution_id=self.studio.job_id, ab_arm=job.get("ab_arm"),
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
        if blocker := request_tool_blocker(studio.prompt, name):
            return {"status": "not_run", "reason": blocker}
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
        self.disclose_selection(route, call_id, name, arguments)
        blocker = self.selection_blocker(name, arguments, route) or blocker
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
            started_at = time.monotonic()
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
                if name == _GATEWAY_SEARCH_TOOL:
                    output = self.filter_discovery(_unwrap_tool_output(output))
                if name.rsplit("___", 1)[-1] in {
                    "query_music_task", "get_music_task", "get_video_task", "get_runway_task",
                    "get_render_progress", "get_task",
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
                        interval = 15 if name == "ModelStudio___get_task" else 8
                        await asyncio.sleep(min(interval, max(0, deadline - time.monotonic())))
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
                if self.matches_media_job(job, name, arguments["job_id"]):
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
        if name != _GATEWAY_SEARCH_TOOL:
            provider, raw_tool = tool_parts(name)
            quote = estimate_cost(name, arguments, list_price=True)
            provider_cents = fee_cents = None
            if completed.status in {"rejected", "dry_run"} or is_free_tool(name):
                provider_cents = fee_cents = 0
            elif quote.total_cents is not None:
                from server.billing_rates import cost_for
                try:
                    cost = cost_for(provider, raw_tool, arguments)
                    provider_cents, fee_cents = cost.provider_cents, cost.fee_cents
                except (ValueError, TypeError, KeyError):
                    pass
            logger.info(json.dumps({
                "event": "provider_call", "entry_point": "gateway_executor",
                "request_id": self.run_scope, "call_id": call_id, "tool": name,
                "provider": provider, "model": effective_model(provider, raw_tool, arguments),
                "status": completed.status,
                "latency_seconds": 0 if rejection is not None else round(time.monotonic() - started_at, 3),
                "provider_cost_estimate_cents": provider_cents, "fee_estimate_cents": fee_cents,
                "total_estimate_cents": quote.total_cents, "currency": "USD",
            }))
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
                    "endpoint_id": payload.get("endpoint_id"),
                    "arguments": arguments, "required": route.required,
                    "asset": self.review_asset(completed, provider, model),
                }
        elif is_free_tool(name) and arguments.get("job_id"):
            for job in self.media_jobs.values():
                if self.matches_media_job(job, name, arguments["job_id"]):
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
