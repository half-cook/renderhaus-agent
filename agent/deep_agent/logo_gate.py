"""Bind logo completion to saved geometry, motion and final-artifact evidence."""
from __future__ import annotations

import hashlib
import json

from agent.deep_agent.routing import route_intent
from providers.ffmpeg.sandbox import input_file, job_directory, sha256_file


LOGO_TOOL = "Logo___logo_vectorize"
_CHANGING_OPS = {"vectorize", "approve", "choreograph"}
_FINISHING_OPS = {"transcode_h264", "mux_aac", "loudnorm_mux_aac", "reframe_crop", "reframe_pad_blur",
                  "burn_subtitles", "color_match_lut", "audio_cleanup", "make_proxy"}


def _changes_logo(event) -> bool:
    return (event.name == LOGO_TOOL and event.arguments.get("op") in _CHANGING_OPS
            or event.name in {"Remotion___render_timeline", "Remotion___deliver_render"}
            or event.name == "Ffmpeg___ffmpeg_tool" and event.arguments.get("op") in _FINISHING_OPS)


def gate_logo_delivery(request, studio, final=None) -> bool | None:
    route = route_intent(request.prompt)
    required = route.skill == "logo-animation" or route.skill in {None, "final-assembly", "remotion-delivery-render", "remotion-deliverable-qc"} and any(
        event.result.get("logo_animation_required") is True for event in studio.tool_events)
    if not required:
        return None
    reports = [event for event in studio.tool_events
               if event.name == LOGO_TOOL and event.arguments.get("op") == "final_frame"]
    last = reports[-1] if reports else None
    result = last.result if last else {}
    reasons = list(result.get("failures") or [])
    passed = False
    try:
        if not last or last.status != "succeeded" or last.arguments.get("job_id") != studio.job_id or result.get("passed") is not True or reasons:
            raise ValueError("No saved passing logo QA report was verified for the current job.")
        directory = job_directory(studio.job_id)
        report_file = input_file(directory, result.get("report_path"), max_bytes=1_000_000)
        records = result.get("outputs") or []
        report_records = [row for row in records if input_file(directory, row.get("path")) == report_file]
        if len(report_records) != 1 or report_records[0].get("sha256") != sha256_file(report_file):
            raise ValueError("The saved logo QA report checksum changed or was not recorded.")
        report = json.loads(report_file.read_text())
        keys = ("passed", "failures", "output_sha256", "svg_sha256", "motion_spec_sha256",
                "final_frame", "actual_motion", "continuity", "declared_easing")
        if any(report.get(key) != result.get(key) for key in keys):
            raise ValueError("Saved logo QA and the tool result disagree.")
        if any(report.get(key, {}).get("passed") is not True
               for key in ("final_frame", "actual_motion", "continuity", "declared_easing")):
            raise ValueError("Final-frame, decoded-motion, continuity and easing checks must all pass.")
        output = input_file(directory, last.arguments["input_path"])
        if output.suffix.lower() != ".mp4" or sha256_file(output) != report["output_sha256"]:
            raise ValueError("The saved logo QA report does not match the current MP4 checksum.")
        from providers.logo_animation.api import vector_bundle

        svg_path = last.arguments["params"]["svg_path"]
        _, manifest = vector_bundle(directory, svg_path, approved=True)
        if manifest["svg_sha256"] != report["svg_sha256"]:
            raise ValueError("The saved logo QA report does not match the approved SVG checksum.")
        svg_file = input_file(directory, svg_path)
        spec_path = svg_file.parent / ("motion-" + report["motion_spec_sha256"][:16]) / "motion_spec.json"
        spec = json.loads(input_file(directory, str(spec_path), max_bytes=1_000_000).read_text())
        spec_hash = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        if spec_hash != report["motion_spec_sha256"]:
            raise ValueError("The motion specification changed after logo QA.")
        if any(_changes_logo(event) for event in studio.tool_events[studio.tool_events.index(last)+1:]):
            raise ValueError("New logo, render or finishing work started after logo QA. Check the current output again.")
        qc_events = [event for event in studio.tool_events if event.name in {"Remotion___deliver_render", "Remotion___qc_deliverable"}]
        if qc_events:
            files = qc_events[-1].result.get("files") or []
            targets = {(input_file(directory, row.get("output_path")), row.get("sha256")) for row in files}
            if targets != {(output, report["output_sha256"])}:
                raise ValueError("Logo QA and deliverable QC must certify the same final MP4 checksum.")
        passed = True
    except (ValueError, OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        if str(exc) and str(exc) not in reasons:
            reasons.append(str(exc))
    if passed:
        return True
    title = "Logo animation QC incomplete"
    message = title + ". " + reasons[0]
    from agent.studio_agent_next import _progress

    _progress(studio, event_id="logo-animation-qc", event_type="RUN_ERROR", title=title,
              message=message[:1000], status="failed")
    if final is not None:
        final.title = title
        final.summary = message[:320]
        final.markdown = ("# " + title + "\n\n" + "\n\n".join(reasons)
                          + "\n\nVisual review remains pending. Recheck the current approved vector and saved MP4 before delivery.")[:30_000]
    return False
