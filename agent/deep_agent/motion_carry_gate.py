"""Enforce the local motion report at the Studio delivery boundary."""
from __future__ import annotations

from pathlib import Path

from agent.deep_agent.routing import route_intent
from providers.remotion.motion_carry import validate_report


MOTION_SKILLS = {"motion-graphics", "product-demo-video", "knowledge-explainer", "hyperframes", "motion-carry-qc"}
PROBE = "Remotion___motion_carry_probe"
FINISHING_OPS = {"transcode_h264", "mux_aac", "loudnorm_mux_aac", "reframe_crop", "reframe_pad_blur"}


def _changes_output(event) -> bool:
    return (event.name.endswith(("render_timeline", "render_composition")) or
            event.name == "Remotion___render_ad_variants" and event.arguments.get("stage") != "plan" or
            event.name == "Remotion___deliver_render" or
            event.name == "Ffmpeg___ffmpeg_tool" and event.arguments.get("op") in FINISHING_OPS)


def requires_motion_qc(prompt, events) -> bool:
    skill = route_intent(prompt).skill
    if skill in MOTION_SKILLS:
        return True
    return skill in {None, "final-assembly", "editing"} and any(
        event.result.get("motion_carry_required") is True for event in events)


def _output_paths(result) -> set[Path]:
    paths = {Path(result["output_path"]).resolve()} if result.get("output_path") else set()
    for key in ("files", "rendered", "outputs"):
        for row in result.get(key) or []:
            value = row.get("output_path") or row.get("file") or row.get("path")
            if value:
                paths.add(Path(value).resolve())
    return paths


def gate_motion_delivery(request, studio, final=None) -> bool | None:
    route = route_intent(request.prompt)
    prior_events = {event["id"]: event for event in request.prior_tool_events}
    current_events = [event for event in studio.tool_events if event.public() != prior_events.get(event.id)]
    probes = [event for event in current_events if event.name == PROBE]
    if not requires_motion_qc(request.prompt, studio.tool_events) and not probes:
        return None
    last = probes[-1] if probes else None
    result = last.result if last else {}
    passed = bool(last and result.get("job_id") == studio.job_id and validate_report(result))
    reasons = list(result.get("failures") or [])
    if passed:
        probe_index = studio.tool_events.index(last)
        if any(_changes_output(event) for event in studio.tool_events[probe_index+1:]):
            passed = False
            reasons.append("New render or finishing work started after motion QC; probe the new output before delivery.")
        work = [event for event in current_events if _changes_output(event)]
        if work:
            latest = work[-1]
            if latest.name.endswith(("render_timeline", "render_composition")):
                polls = [event for event in current_events[current_events.index(latest)+1:]
                         if event.name.endswith("get_render_progress") and event.result.get("status") == "succeeded"
                         and latest.result.get("render_id")
                         and event.result.get("render_id") == latest.result["render_id"]]
                targets = _output_paths(polls[-1].result) if polls else set()
            else:
                targets = _output_paths(latest.result)
            if targets != {Path(result["input_path"]).resolve()}:
                passed = False
                reasons.append("The motion report must match the latest rendered or finished output. Multi-output motion delivery needs separate verified reports and remains incomplete here.")
        artifacts = [event for event in current_events if event.name.endswith("get_render_progress")
                     and event.result.get("status") == "succeeded"]
        if artifacts and not work:
            current = artifacts[-1].result.get("output_path")
            if not current or Path(current).resolve() != Path(result["input_path"]).resolve():
                passed = False
                reasons.append("The saved motion report does not match the current rendered MP4.")
    if passed:
        return True
    failed = result.get("status") == "failed" and bool(result.get("failures"))
    title = "Motion carry QC failed" if failed else "Motion carry QC incomplete"
    if not reasons:
        reasons = [result.get("reason") or "No current saved passing motion report and matching MP4 checksum were verified."]
    renderer = "hyperframes_render" if route.skill == "hyperframes" or "hyperframes" in request.prompt.lower() else "remotion_render"
    message = title + ". " + reasons[0]
    from agent.studio_agent_next import _progress

    _progress(studio, event_id="motion-carry-qc", event_type="RUN_ERROR", title=title,
              message=message[:1000], status="failed")
    if final is not None:
        final.title = title
        final.summary = message[:320]
        final.markdown = (f"# {title}\n\n" + "\n\n".join(reasons) +
            (f"\n\nSaved report: `{result['report_path']}`." if result.get("report_path") else "") +
            f"\n\nI can re-render with `{renderer}` after these fixes, then run `motion_carry_probe` again. "
            "Rendering keeps its existing approval and cost controls. Visual review remains pending.")[:30_000]
    return False
