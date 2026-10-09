#!/usr/bin/env python3
"""Fast CI checks that do not call paid providers."""

from __future__ import annotations

import io
import asyncio
import os
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _force_dry_run() -> None:
    os.environ["KLING_DRY_RUN"] = "true"
    os.environ["RUNWAY_DRY_RUN"] = "true"
    os.environ["LUMA_DRY_RUN"] = "true"
    os.environ["SEEDANCE_DRY_RUN"] = "true"
    os.environ["SEEDREAM_DRY_RUN"] = "true"
    os.environ["ELEVENLABS_DRY_RUN"] = "true"
    os.environ["FISH_AUDIO_DRY_RUN"] = "true"
    os.environ["REMOTION_DRY_RUN"] = "true"
    os.environ["FAL_DRY_RUN"] = "true"
    os.environ["OPENAI_IMAGES_DRY_RUN"] = "true"
    os.environ["HYPERFRAMES_DRY_RUN"] = "true"
    os.environ["MODELSTUDIO_DRY_RUN"] = "true"
    os.environ["SYNC_DRY_RUN"] = "true"
    os.environ["HEYGEN_DRY_RUN"] = "true"
    os.environ["TOPAZ_DRY_RUN"] = "true"
    os.environ["MUREKA_DRY_RUN"] = "true"
    os.environ["MUREKA_MODEL"] = "mureka-9.5"


_force_dry_run()


def check_gateway_tools_schema() -> None:
    from providers.catalog import PROVIDERS
    from providers.registry import (
        generate_schemas,
        is_forbidden_gateway_tool,
        load_committed_schemas,
    )

    for spec in PROVIDERS:
        generated = generate_schemas(spec)
        committed = load_committed_schemas(spec)
        assert committed == generated, (
            f"schema drift for {spec.id}: run python scripts/generate_gateway_schemas.py"
        )
        names = [tool["name"] for tool in committed]
        forbidden = [name for name in names if is_forbidden_gateway_tool(name)]
        assert not forbidden, f"{spec.id} Gateway schema includes wait tools: {forbidden}"
        for tool in generated:
            input_schema = tool.get("inputSchema") or {}
            _assert_gateway_shape(input_schema)
            properties = input_schema.get("properties") or {}
            required = input_schema.get("required") or []
            missing = [name for name in required if name not in properties]
            assert not missing, (
                f"{spec.id}.{tool['name']} required fields missing from properties: {missing}"
            )
        print(f"ok {spec.id} gateway schema ({len(names)} tools)")


def check_routing_inventory() -> None:
    import json
    import yaml

    from agent.deep_agent.routing import POLICY, TOOL_MAP
    from agent.deep_agent.runner import DISPATCH_TARGETS, SKILLS_ROOT
    from providers.catalog import PROVIDERS
    from providers.registry import load_committed_schemas

    assert len(PROVIDERS) == 14
    assert sum(len(load_committed_schemas(spec)) for spec in PROVIDERS) == 108
    paths = list(SKILLS_ROOT.glob("*/SKILL.md"))
    assert len(paths) == 24
    assert "ladder" not in POLICY and "premium_targets" not in POLICY
    assert "project_policy" not in POLICY and "flux2_klein4b_t2i" not in TOOL_MAP
    for capability, choice in POLICY["capability_map"].items():
        assert set(choice) == {"default", "exceptions", "interim", "ab_candidates"}, capability
        selected = [choice["default"], choice["interim"]] + [row["tool"] for row in choice["exceptions"]]
        for alias in filter(None, selected):
            assert TOOL_MAP[alias]["status"] in {"ready", "pending"}, alias
        if choice["interim"]:
            assert TOOL_MAP[choice["interim"]]["status"] == "ready", capability
    for path in paths:
        metadata = yaml.safe_load(path.read_text().split("---", 2)[1])["metadata"]
        assert set(metadata["include_tools"].split()) <= DISPATCH_TARGETS.keys(), path
        assert all(TOOL_MAP[alias]["status"] != "retired" for alias in metadata["routing_tools"].split()), path
    cases = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
    assert len(cases) == 129 and sum(not case["skip_reason"] for case in cases) == 116
    print("ok routing inventory (14 providers, 108 Gateway tools, 24 skills, 116 active routing rows)")


def _assert_gateway_shape(schema: object) -> None:
    if not isinstance(schema, dict):
        return
    extra = set(schema) - {"type", "properties", "required", "items", "description"}
    assert not extra, f"Gateway schema has unsupported keys: {sorted(extra)}"
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for child in properties.values():
            _assert_gateway_shape(child)
    _assert_gateway_shape(schema.get("items"))


def check_dry_run_dispatch() -> None:
    _force_dry_run()
    from providers.catalog import PROVIDERS
    from providers.registry import dispatch, dummy_arguments, load_committed_schemas

    for spec in PROVIDERS:
        if spec.id == "elevenlabs":
            # Upstream constraints need meaningful inputs, covered by test_elevenlabs.py.
            result = dispatch(spec.id, "music_compose", {"prompt": "Warm piano", "music_length_ms": 3000})
            assert result["status"] == "dry_run"
            continue
        mureka_jobs = {}
        heygen_job_id = None
        topaz_job_id = None
        for schema in load_committed_schemas(spec):
            name = schema["name"]
            arguments = dummy_arguments(schema)
            if spec.id == "mureka":
                arguments = {"generate_song": {"lyrics": "[Verse]\nOffline song"},
                             "generate_instrumental": {"prompt": "Gentle piano"},
                             "generate_lyrics_video": {"song_id": "song_ci"},
                             "get_music_task": {"job_id": mureka_jobs.get("generate_song", "")},
                             "get_video_task": {"job_id": mureka_jobs.get("generate_lyrics_video", "")},
                             "list_mureka_models": {}}[name]
            if spec.id == "topaz" and name in {"upscale_video", "interpolate_video"}:
                arguments.update(video_url="https://example.test/source.mp4", source_duration_seconds=10.0,
                                 source_fps=30.0, source_width=960, source_height=540)
            if spec.id == "topaz" and name == "get_video_task":
                assert topaz_job_id, "Topaz poll must reuse a submitted dry-run handle"
                arguments["job_id"] = topaz_job_id
            if spec.id == "heygen" and name == "create_avatar_video":
                arguments.update(avatar_id="lk_ci", voice_id="voice_ci", script="Offline presenter preview",
                                 duration_seconds=90.0, subjects="Authorized test presenter and voice",
                                 consent_confirmed=True, consent_record_id="ci-consent")
            if spec.id == "heygen" and name == "get_video_status":
                assert heygen_job_id, "HeyGen poll must reuse the created dry-run handle"
                arguments["job_id"] = heygen_job_id
            if spec.id == "sync" and name == "lipsync_video":
                arguments.update(video_url="https://example.test/source.mp4",
                                 audio_url="https://example.test/voice.wav",
                                 source_duration_seconds=5.0, audio_duration_seconds=5.0,
                                 source_fps=25.0, subjects="Synthetic test face and authorized synthetic voice",
                                 consent_confirmed=True)
            if spec.id == "sync" and name == "get_video_task":
                arguments["job_id"] = "sync:dry:00000000000000000000000000000000"
            if spec.id == "seedance" and name in {"text_to_video", "image_to_video", "reference_to_video", "edit_video", "extend_video"}:
                arguments["model"] = "dreamina-seedance-2-5-260628"
            if spec.id == "seedance" and name in {"edit_video", "extend_video"}:
                arguments.update({"video_url": "https://example.test/source.mp4",
                                  "source_duration_seconds": 5, "source_fps": 24,
                                  "source_aspect_ratio": "16:9"})
            if spec.id == "kling":
                if name == "image_to_video":
                    arguments["image_path_or_url"] = "https://example.test/frame.png"
                elif name == "get_video_task":
                    arguments["job_id"] = "current:text_to_video:ci-smoke"
            if spec.id == "runway":
                if name == "act_two":
                    arguments = {"character_uri": "https://example.com/character.png",
                                 "performance_uri": "https://example.com/performance.mp4",
                                 "performance_duration_seconds": 5, "subjects": "Authorized performer",
                                 "consent_confirmed": True}
                for field in ("image_path_or_url", "video_path_or_url"):
                    if field in arguments:
                        arguments[field] = "https://example.com/source.mp4" if field.startswith("video") else "https://example.com/source.png"
                if "video_duration_seconds" in arguments:
                    arguments["video_duration_seconds"] = 2.0
                if name == "get_runway_task":
                    arguments["job_id"] = "00000000-0000-4000-8000-000000000000"
            if spec.id == "fal":
                if name == "kling_motion_control":
                    arguments = {"image_url": "https://example.com/character.png",
                                 "video_url": "https://example.com/performance.mp4",
                                 "performance_duration_seconds": 5, "subjects": "Authorized performer",
                                 "consent_confirmed": True}
                if name == "get_video_task":
                    arguments["job_id"] = "fal-ai/wan-vace-14b:ci-smoke"
                elif name in {"vidu_q4_i2v", "generate_wan3_i2v"}:
                    arguments["start_image_url" if name == "generate_wan3_i2v" else "image_url"] = "https://example.test/frame.png"
                elif name == "video_to_video":
                    arguments["prompt"] = "A small offline smoke test"
            if spec.id == "alibaba_modelstudio":
                if name == "get_task":
                    arguments["job_id"] = "00000000-0000-4000-8000-000000000000"
                else:
                    arguments.update({"video_url": "https://example.test/source.mp4",
                                      "source_duration_seconds": 5, "source_fps": 24})
            if spec.id == "remotion" and name == "prepare_conversational_edit":
                arguments = {
                    "title": "Offline interview cut", "plan_summary": "Keep the greeting with subtitles.",
                    "sources": [{"id": "source", "url": "https://example.test/source.mp4",
                                 "duration_seconds": 1,
                                 "words": [{"text": "Hello", "start": 0.1, "end": 0.5}]}],
                    "segments": [{"source_id": "source", "first_word": 0, "last_word": 0}],
                }
            result = dispatch(spec.id, name, arguments)
            if spec.id == "mureka" and name.startswith("generate_"):
                mureka_jobs[name] = result["job_id"]
            assert isinstance(result, dict), f"{spec.id}.{name} did not return a dict"
            if spec.id == "heygen" and name == "create_avatar_video":
                heygen_job_id = result["job_id"]
            if spec.id == "topaz" and name in {"upscale_video", "interpolate_video"}:
                topaz_job_id = result["job_id"]
            if "error" in result and result.get("error_type"):
                raise AssertionError(f"{spec.id}.{name} dispatch error: {result}")
            print(f"ok dry-run {spec.id}.{name} status={result.get('status', 'ok')}")


def check_hyperframes_preview() -> None:
    from agent.hyperframes import HYPERFRAMES_TOOL, HyperFramesServer

    server = HyperFramesServer()
    os.environ["HYPERFRAMES_ENABLED"] = "false"
    assert asyncio.run(server.list_tools()) == []
    os.environ["HYPERFRAMES_ENABLED"] = "true"
    try:
        tools = asyncio.run(server.list_tools())
        assert [tool.name for tool in tools] == [HYPERFRAMES_TOOL.name]
        result = asyncio.run(server.call_tool(HYPERFRAMES_TOOL.name, {
            "html": "<!doctype html><html><body>Offline title</body></html>",
            "duration_seconds": 2, "width": 1280, "height": 720, "fps": 30,
        }))
        assert result["status"] == "dry_run"
        assert not {"url", "output_path", "job_id", "render_id"} & result.keys()
    finally:
        os.environ["HYPERFRAMES_ENABLED"] = "false"
    print("ok local HyperFrames schema and dry-run composition preview")


def check_imports() -> None:
    from lambdas import handler as generic_handler
    from providers.elevenlabs import api as elevenlabs_api
    from server import app, config  # noqa: F401

    assert callable(generic_handler.handler)
    assert isinstance(elevenlabs_api.dry_run(), bool)
    print("ok python imports")


def check_lambda_zip() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "deploy_gateway", ROOT / "scripts" / "deploy_gateway.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scripts/deploy_gateway.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    zip_bytes = module.build_lambda_zip()
    assert zip_bytes[:2] == b"PK", "lambda zip is not a zip archive"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
    assert "server/billing_rates.py" in names, "lambda zip is missing shared Q4 billing rates"
    linux_native = [
        name
        for name in names
        if "pydantic_core" in name and name.endswith(".so") and "linux" in name
    ]
    assert linux_native, (
        "lambda zip is missing a Linux pydantic_core native module; "
        "pip-install with --platform manylinux2014_aarch64 --python-version 3.11"
    )
    otio_native = [
        name for name in names
        if name.startswith("opentimelineio/") and name.endswith(".so") and "aarch64" in name
    ]
    assert otio_native, "lambda zip is missing the Linux aarch64 OpenTimelineIO native module"
    print(f"ok lambda zip ({len(zip_bytes)} bytes)")


def main() -> int:
    check_gateway_tools_schema()
    check_routing_inventory()
    check_imports()
    check_dry_run_dispatch()
    check_hyperframes_preview()
    check_lambda_zip()
    print("ci_check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ci_check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
