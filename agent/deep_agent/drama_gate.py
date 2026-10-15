"""Host-owned approvals and exact production plans for episodic fiction."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal

from agent.deep_agent.routing import estimate_cost, intent_constraints, is_free_tool, job_type, tool_parts
from agent.deep_agent.short_drama import check_episode, check_outline
from providers.catalog import get_provider
from providers.contracts import validate_tool_arguments
from providers.registry import load_committed_schemas


def signature(name: str, arguments: dict) -> str:
    return hashlib.sha256(json.dumps([name, arguments], sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class DramaGate:
    def __init__(self, saved: dict | None = None, *, active: bool | None = None):
        self.state = deepcopy(saved or {})
        was_active = self.state.pop("active", bool(self.state))
        self.active = was_active if active is None else active

    def invalidate_batch(self) -> None:
        self.state["jobs"] = []

    def approve_outline(self, outline: dict) -> dict:
        result = check_outline(outline)
        if not result["ok"]:
            return result
        self.active = True
        if self.state.get("outline_hash") != result["outline_hash"]:
            self.state = {"outline_hash": result["outline_hash"], "outline": result["outline"],
                          "locks": {}, "jobs": [], "submitted": self.state.get("submitted", [])}
        return {"ok": True, "outline_hash": result["outline_hash"],
                "message": "Outline approved. Production still requires a validated batch and spending approval."}

    def prepare(self, episode: dict, jobs: list[dict]) -> dict:
        self.active = True
        self.invalidate_batch()
        result = check_episode(episode)
        if not result["ok"]:
            return result
        errors = []
        if not self.state.get("outline_hash") or episode["outline_hash"] != self.state["outline_hash"]:
            errors.append("Approve the current outline before preparing production.")
        else:
            outline = self.state["outline"]
            if episode["episode_id"] not in {row["id"] for row in outline["episodes"]}:
                errors.append("The episode is absent from the approved outline.")
            if not {row["id"] for row in episode["characters"]} <= set(outline["cast"]):
                errors.append("The character roster differs from the approved outline.")
            if not {row["id"] for row in episode["art"]} <= set(outline["assets"]):
                errors.append("The location or prop roster differs from the approved outline.")
        locks = {row["id"]: row for row in episode["locks"]}
        depicted = {subject for segment in episode["segments"] for cut in segment["cuts"]
                    for subject in cut["subjects"]}
        for key, previous in self.state.get("locks", {}).items():
            if previous["subject_id"] in depicted and previous != locks.get(key):
                errors.append(f"Continuity lock {key} changed. Approve a revised outline before changing the bible.")
        if not isinstance(jobs, list) or not jobs:
            errors.append("Declare the exact jobs for this production batch.")
            jobs = []
        checked_jobs, ids = [], set()
        for job in jobs:
            try:
                checked = self._job(episode, job)
                if checked["id"] in ids:
                    raise ValueError("Production job IDs must be unique.")
                ids.add(checked["id"])
                checked_jobs.append(checked)
            except (ValueError, KeyError, TypeError) as exc:
                errors.append(str(exc))
        if errors:
            return {**result, "ok": False, "errors": errors}
        self.state.update({"episode": result["episode"], "jobs": checked_jobs,
                           "locks": {**self.state.get("locks", {}), **locks}})
        return {**result, "jobs": checked_jobs,
                "message": "Batch validated. No media generated. Each paid job still needs approval."}

    @staticmethod
    def _job(episode: dict, job: dict) -> dict:
        if not isinstance(job, dict) or set(job) - {"id", "tool_name", "arguments", "segment_id", "cut_id", "line_id"}:
            raise ValueError("A job requires id, tool_name, arguments and its script or storyboard reference.")
        if not isinstance(job.get("id"), str) or not job["id"].strip():
            raise ValueError("A production job requires a nonempty id.")
        name, arguments = job["tool_name"], job["arguments"]
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("A production job requires a tool name and arguments object.")
        provider, verb = tool_parts(name)
        spec = get_provider(provider)
        if name != spec.target_name + "___" + verb:
            raise ValueError("Use the exact discovered Gateway tool name.")
        schema = next((row["inputSchema"] for row in load_committed_schemas(spec) if row["name"] == verb), None)
        if schema is None or is_free_tool(name):
            raise ValueError("Production batches contain existing paid tools only; polling and checks stay separate.")
        validate_tool_arguments(provider, verb, arguments, schema)
        segments = {row["id"]: row for row in episode["segments"]}
        cuts = {row["id"]: row for segment in segments.values() for row in segment["cuts"]}
        kind = job_type(name)
        if kind in {"t2v", "i2v", "reference_video", "v2v_edit", "extend"}:
            segment = segments.get(job.get("segment_id"))
            if segment is None:
                raise ValueError("Every video job must name its storyboard segment.")
            seconds = arguments.get("duration", arguments.get("duration_seconds"))
            if seconds == -1:
                seconds = arguments.get("source_duration_seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 2 <= seconds <= 15:
                raise ValueError("Each video job requires a known duration of 2-15 seconds.")
            expected = sum(Decimal(str(cut["duration_seconds"])) for cut in segment["cuts"])
            if Decimal(str(seconds)) != expected:
                raise ValueError("Video job duration must equal its storyboard segment duration.")
            if arguments.get("prompt") != "\n".join(cut["video_prompt"] for cut in segment["cuts"]):
                raise ValueError("Video job prompt must match the segment's locked prompts verbatim.")
        elif kind in {"still_image", "image_edit"}:
            cut = cuts.get(job.get("cut_id"))
            if cut is None or arguments.get("prompt") != cut["keyframe_prompt"]:
                raise ValueError("Image job must match its cut's locked keyframe prompt verbatim.")
        elif kind in {"tts", "cloned_tts"}:
            line = next((row for row in episode["script"] if row["id"] == job.get("line_id")), None)
            if line is None or line["kind"] != "dialogue" or arguments.get("text") != line["text"]:
                raise ValueError("Voice job must reference a dialogue line and preserve its text verbatim.")
        elif kind == "lipsync":
            segment = segments.get(job.get("segment_id"))
            if segment is None:
                raise ValueError("Lip-sync jobs must name their storyboard segment.")
            expected = sum(Decimal(str(cut["duration_seconds"])) for cut in segment["cuts"])
            if Decimal(str(arguments.get("source_duration_seconds", 0))) != expected:
                raise ValueError("Lip-sync source duration must match its storyboard segment.")
            if not 0 < arguments.get("audio_duration_seconds", 0) <= 15:
                raise ValueError("Lip-sync audio must be measured and at most 15 seconds.")
        elif kind not in {"music", "motion_graphics"}:
            raise ValueError("This tool has no supported job contract in the series workflow. No submission is authorized.")
        quote = estimate_cost(name, arguments)
        return {**deepcopy(job), "signature": signature(name, arguments),
                "estimated_cost_cents": quote.total_cents}

    def requires_approval(self, name: str) -> bool:
        return self.active and not is_free_tool(name)

    def selection_constraints(self, prompt: str, name: str, arguments: dict, original: dict) -> dict:
        if not self.active or job_type(name) not in {"t2v", "i2v", "reference_video", "v2v_edit", "extend"}:
            return original
        shot = intent_constraints(arguments.get("prompt", ""), arguments=arguments)
        shot["predicates"]["real_face_refs"] |= original["predicates"]["real_face_refs"]
        for key in ("provider", "model", "named_model"):
            shot[key] = original[key]
        shot["required"] = {**{key: value for key, value in original["required"].items()
                               if key != "duration_seconds"}, **shot["required"]}
        return shot

    def _submission_key(self, row: dict) -> str:
        return "/".join((self.state["episode"]["episode_id"], row["id"], row["signature"]))

    def claim_submission(self, name: str, arguments: dict) -> str | None:
        if not self.requires_approval(name):
            return None
        key = signature(name, arguments)
        submitted = self.state.setdefault("submitted", [])
        for row in self.state.get("jobs", []):
            if row["signature"] == key and self._submission_key(row) not in submitted:
                claim = self._submission_key(row)
                submitted.append(claim)
                return claim
        return None

    def release_submission(self, claim: str | None) -> None:
        if claim is not None:
            self.state["submitted"].remove(claim)

    def blocker(self, name: str, arguments: dict) -> str | None:
        if not self.requires_approval(name):
            return None
        if not self.state.get("outline_hash"):
            return "Approve the series outline before production. No paid job was submitted."
        try:
            key = signature(name, arguments)
        except (ValueError, TypeError):
            return "Production arguments must be finite JSON values."
        if not any(row["signature"] == key and self._submission_key(row) not in self.state.get("submitted", [])
                   for row in self.state.get("jobs", [])):
            return "Validate this exact episode batch before spending. Changed prompts, references or settings need a new batch."
        return None

    def snapshot(self) -> dict:
        return {"active": self.active, **deepcopy(self.state)} if self.active or self.state else {}
