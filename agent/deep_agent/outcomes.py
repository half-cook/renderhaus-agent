from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

from agent.deep_agent.routing import training_eligible


class OutcomeStore:
    def __init__(self, directory: Path | None = None):
        self.path = (directory or Path(os.getenv("RENDERHAUS_OUTCOME_DIR", ".renderhaus/provider-outcomes"))) / "outcomes.jsonl"

    def record(self, *, event_id: str, provider: str, model: str, job_type: str,
               outcome: str, stage: str, provider_job_id: str | None = None,
               asset: dict | None = None, workspace_id: str | None = None,
               project_id: str | None = None, execution_id: str | None = None) -> dict:
        if outcome not in {"accepted", "rejected"} or stage not in {"approval", "review"}:
            raise ValueError("Outcome must be accepted/rejected with approval/review stage.")
        asset = asset or {}
        eligible = bool(stage == "review" and outcome == "accepted" and
                        isinstance(asset.get("version_id"), str) and asset["version_id"] and
                        asset.get("provider") == provider and asset.get("model") == model and
                        training_eligible(asset))
        row = {"event_id": event_id, "timestamp": int(time.time()), "provider": provider,
               "model": model, "job_type": job_type, "provider_job_id": provider_job_id,
               "outcome": outcome, "stage": stage, "workspace_id": workspace_id,
               "project_id": project_id, "execution_id": execution_id,
               "version_id": asset.get("version_id"), "training_eligible": eligible}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            for line in stream:
                previous = json.loads(line)
                if (previous["event_id"], previous["workspace_id"], previous["project_id"]) == (
                    event_id, workspace_id, project_id,
                ):
                    return previous
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return row
