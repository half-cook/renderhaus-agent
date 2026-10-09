from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCORES_PATH = ROOT / "docs/continuity_qc_benchmark_scores.json"
EVAL_PATH = Path(__file__).with_name("continuity_qc_vlm_eval.json")
REQUIRED_PAIRS = 420
MIN_ACCURACY = 0.85


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_hash(pairs: list[dict]) -> str:
    refs = [{key: row.get(key) for key in ("id", "a", "b", "perturbation")}
            for row in sorted(pairs, key=lambda row: row["id"])]
    return hashlib.sha256(json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def eval_identity() -> dict[str, Any]:
    from agent.deep_agent.continuity_qc import CALIBRATION_PATH
    from agent.deep_agent.routing import POLICY
    from providers.gemini.contracts import RUBRIC_HASH, VERIFIED_MODEL, GeminiJudgement, GENERATION_CONFIG
    import os

    return {"model": os.getenv("GEMINI_VLM_MODEL", VERIFIED_MODEL), "rubric_sha256": RUBRIC_HASH,
            "inference_sha256": hashlib.sha256(json.dumps({"generation_config": GENERATION_CONFIG,
                "schema": GeminiJudgement.model_json_schema()}, sort_keys=True).encode()).hexdigest(),
            "dinov3_enabled": POLICY["continuity_qc"]["dinov3_enabled"],
            "dataset_sha256": file_hash(SCORES_PATH), "calibration_sha256": file_hash(CALIBRATION_PATH),
            "manifest_sha256": POLICY["continuity_qc"]["vlm_eval_gate"]["manifest_sha256"],
            "inputs_sha256": POLICY["continuity_qc"]["vlm_eval_gate"]["inputs_sha256"],
            "prefilter_threshold": POLICY["continuity_qc"]["vlm_prefilter_threshold"]}


def eval_report(decisions: list[dict], *, live: bool = False) -> dict[str, Any]:
    """Score against frozen labels. Skips remain in the denominator."""
    from providers.gemini.contracts import GeminiJudgement
    from agent.deep_agent.continuity_qc import ContinuityConfig, DINO_MODEL, load_calibration

    canonical = json.loads(SCORES_PATH.read_text())["pairs"]
    config = ContinuityConfig(backend="local")
    calibration = load_calibration()
    labels = {row["id"]: row for row in canonical}
    seen = set()
    correct = cascade_correct = 0
    categories: dict[str, dict] = {}
    complete = len(decisions) == REQUIRED_PAIRS
    for row in canonical:
        categories.setdefault(row["category"], {"pairs": 0, "completed": 0, "accepted": 0, "correct": 0})["pairs"] += 1
    for decision in decisions:
        pair_id = decision.get("id")
        row = labels.get(pair_id)
        valid = (row is not None and pair_id not in seen and decision.get("status") == "completed"
                 and type(decision.get("same_shot_continuity")) is bool
                 and type(decision.get("cascade_accepted")) is bool)
        seen.add(pair_id)
        if not valid:
            complete = False
            continue
        try:
            GeminiJudgement.model_validate({key: decision[key] for key in GeminiJudgement.model_fields})
        except (ValueError, KeyError):
            complete = False
            continue
        _, siglip, dino = calibration.decide(row["siglip"], row["dinov2"], DINO_MODEL, config)
        cascade = (decision["same_shot_continuity"]
                   and (siglip + dino) / 2 >= config.vlm_prefilter_threshold)
        if decision["cascade_accepted"] != cascade:
            complete = False
        expected = row["label"] == "consistent"
        right = decision["same_shot_continuity"] == expected
        correct += right
        cascade_correct += cascade == expected
        cat = categories[row["category"]]
        cat["completed"] += 1
        cat["accepted"] += decision["same_shot_continuity"]
        cat["correct"] += right
    for cat in categories.values():
        cat["acceptance_rate"] = cat["accepted"] / cat["pairs"]
        cat["accuracy"] = cat["correct"] / cat["pairs"]
    return {**eval_identity(), "schema_version": 1, "live": live, "pairs": REQUIRED_PAIRS,
            "complete": complete and seen == set(labels), "accuracy": correct / REQUIRED_PAIRS,
            "cascade_accuracy": cascade_correct / REQUIRED_PAIRS, "per_category": categories,
            "decisions": decisions}


def eval_qualifies(result: dict[str, Any]) -> bool:
    from providers.gemini.contracts import VERIFIED_MODEL

    try:
        identity = eval_identity()
        if (not isinstance(result, dict) or result.get("live") is not True
                or result.get("schema_version") != 1 or identity["model"] != VERIFIED_MODEL
                or identity["dinov3_enabled"] is not False
                or any(result.get(key) != value for key, value in identity.items())):
            return False
        recomputed = eval_report(result["decisions"], live=True)
        return (recomputed["complete"] and recomputed["accuracy"] > MIN_ACCURACY
                and recomputed["cascade_accuracy"] > MIN_ACCURACY)
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        return False


def default_vlm_enabled() -> bool:
    from agent.deep_agent.routing import POLICY

    expected = POLICY["continuity_qc"]["vlm_eval_gate"].get("result_sha256")
    try:
        if not expected or file_hash(EVAL_PATH) != expected:
            return False
        return eval_qualifies(json.loads(EVAL_PATH.read_text()))
    except (OSError, ValueError, TypeError, RecursionError):
        return False
