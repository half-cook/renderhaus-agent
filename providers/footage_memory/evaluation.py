"""Offline timestamp scoring for fictional held-out footage queries.

Synthetic smoke tests validate the evaluator, not a candidate model's quality.
Future externally produced predictions can be scored without loading a backend.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from providers.footage_memory.backends import MediaWindow, get_backend


def generate_fixtures() -> dict:
    examples = (
        (
            "m01",
            "Find the moment the red cup falls.",
            "The red cup falls onto the table.",
            12.0,
            "moment",
        ),
        ("m02", "Find the moment the bell rings.", "The brass bell rings twice.", 37.0, "sound"),
        (
            "m03",
            "Find the moment a yellow kite appears.",
            "A yellow kite appears above the field.",
            48.0,
            "object",
        ),
        (
            "m04",
            "Find the moment the sign reads North gate.",
            "The sign reads North gate.",
            8.0,
            "on_screen_text",
        ),
        (
            "m05",
            "Find the moment someone mentions the bakery.",
            "I used to visit the bakery every morning.",
            25.0,
            "dialogue",
        ),
        (
            "m06",
            "Find the moment a purple train arrives.",
            "A purple train arrives at the platform.",
            53.0,
            "moment",
        ),
    )
    templates = (
        ("person", 0.0, 1.0, "Guest wearing a green sweater.", "guest"),
        ("object", 0.1, 0.6, "A notebook rests on the table.", None),
        ("location", 0.0, 1.0, "An interview room with a whiteboard.", None),
        ("dialogue", 0.2, 0.4, "I remember my childhood and the garden at home.", "guest"),
        ("sound", 0.4, 0.5, "Non-speech laughter from the guest.", None),
        ("on_screen_text", 0.5, 0.7, "Whiteboard reads Launch plan.", None),
        ("moment", 0.7, 0.9, "The guest gestures toward the whiteboard.", None),
    )
    return {
        "version": 1,
        "provenance": "Generated fictional events; no real footage or vendor data.",
        "event_templates": [
            {
                "kind": kind,
                "start_fraction": start,
                "end_fraction": end,
                "speaker_id": speaker,
                "text": text,
                "confidence": 0.6,
                "attrs": {"label": "Guest"} if kind == "person" else {},
            }
            for kind, start, end, text, speaker in templates
        ],
        "media": [
            {
                "id": clip_id,
                "duration_s": 60,
                "events": [
                    {
                        "kind": kind,
                        "t0_ms": int(t0 * 1000),
                        "t1_ms": int((t0 + 1) * 1000),
                        "text": text,
                        "speaker_id": "guest" if kind == "dialogue" else None,
                    },
                    {
                        "kind": "object",
                        "t0_ms": 35000,
                        "t1_ms": 36000,
                        "text": "The blue cup sits on a shelf.",
                    },
                ],
            }
            for clip_id, _query, text, t0, kind in examples
        ],
        "cases": [
            {"id": f"q{index:02d}", "clip_id": clip_id, "query": query, "split": "held_out"}
            for index, (clip_id, query, _text, _t0, _kind) in enumerate(examples, start=1)
        ],
        "labels": [
            {"query_id": f"q{index:02d}", "clip_id": clip_id, "t0_s": t0}
            for index, (clip_id, _query, _text, t0, _kind) in enumerate(examples, start=1)
        ],
    }


def load_fixtures(path: Path | None = None) -> dict:
    selected = path or Path(__file__).with_name("fixtures.json")
    result = json.loads(selected.read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("version") != 1:
        raise ValueError("Invalid footage evaluation fixture version.")
    if not all(isinstance(result.get(key), list) for key in ("cases", "media", "labels")):
        raise ValueError("Invalid footage evaluation fixture collections.")
    return result


def _records(values: list[dict]) -> list[tuple[str, str, float]]:
    if not isinstance(values, list):
        raise ValueError("Timestamp records must be a list.")
    result = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Timestamp record must be an object.")
        query_id, clip_id, t0 = (value.get(key) for key in ("query_id", "clip_id", "t0_s"))
        if any(
            not isinstance(identifier, str) or not identifier.strip()
            for identifier in (query_id, clip_id)
        ):
            raise ValueError("Timestamp records require nonempty query and clip identifiers.")
        if (
            isinstance(t0, bool)
            or not isinstance(t0, (int, float))
            or not math.isfinite(t0)
            or t0 < 0
        ):
            raise ValueError("Timestamp records require a finite nonnegative start time.")
        result.append((query_id, clip_id, float(t0)))
    return result


def score_predictions(
    labels: list[dict], predictions: list[dict], *, tolerance_s: float = 2.0
) -> dict:
    if (
        isinstance(tolerance_s, bool)
        or not isinstance(tolerance_s, (int, float))
        or not math.isfinite(tolerance_s)
        or tolerance_s < 0
    ):
        raise ValueError("Timestamp tolerance must be a finite nonnegative number.")
    truth = _records(labels)
    predicted = _records(predictions)
    if len(set(truth)) != len(truth):
        raise ValueError("Duplicate timestamp labels are invalid.")
    targets = defaultdict(list)
    sources = defaultdict(list)
    for query, clip, timestamp in truth:
        targets[query, clip].append(timestamp)
    for query, clip, timestamp in predicted:
        sources[query, clip].append(timestamp)
    true_positives = 0
    for key, times in sources.items():
        truth_times = sorted(targets[key])
        candidates = sorted(set(times))
        truth_index = prediction_index = 0
        while truth_index < len(truth_times) and prediction_index < len(candidates):
            target = truth_times[truth_index]
            prediction = candidates[prediction_index]
            if prediction < target - tolerance_s:
                prediction_index += 1
            elif prediction > target + tolerance_s:
                truth_index += 1
            else:
                true_positives += 1
                truth_index += 1
                prediction_index += 1
    return {
        "tolerance_s": float(tolerance_s),
        "true_positives": true_positives,
        "false_positives": len(predicted) - true_positives,
        "false_negatives": len(truth) - true_positives,
        "duplicate_predictions": sum(count - 1 for count in Counter(predicted).values()),
        "label_count": len(truth),
        "prediction_count": len(predicted),
        "precision": true_positives / len(predicted) if predicted else 0.0,
        "recall": true_positives / len(truth) if truth else 0.0,
    }


def evaluate_backends(
    names: list[str] | None = None,
    *,
    fixtures: dict | None = None,
    predictions: dict[str, list[dict]] | None = None,
) -> dict:
    data = fixtures if fixtures is not None else load_fixtures()
    if predictions is None:
        predictions = {}
        sources = {media["id"]: media for media in data["media"]}
        for name in names if names is not None else ["mock", "gemini"]:
            backend = get_backend(name)
            predicted = []
            for case in data["cases"]:
                source = sources[case["clip_id"]]
                media = MediaWindow(
                    Path(case["clip_id"] + ".mp4"),
                    0,
                    source["duration_s"],
                    hashlib.sha256(case["clip_id"].encode()).hexdigest(),
                    source["id"],
                )
                answer = backend.answer(case["query"], media)
                if answer["verdict"] == "verified":
                    predicted.append(
                        {"query_id": case["id"], "clip_id": case["clip_id"], "t0_s": answer["t0_s"]}
                    )
            predictions[name] = predicted
    return {
        "fixture_version": data["version"],
        "synthetic_only": True,
        "default_promoted": False,
        "promotion_gate": "Real held-out footage review and service-term clearance remain required.",
        "backends": {
            name: score_predictions(data["labels"], values)
            for name, values in sorted(predictions.items())
        },
    }
