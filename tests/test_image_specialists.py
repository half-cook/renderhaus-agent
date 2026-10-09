from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from mcp import Tool

from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, StudioNode,
    _context_from_request,
)
from providers.fal import api as fal
from providers.registry import dispatch, generate_schemas
from providers.catalog import get_provider
from server.billing_rates import cost_for
from test_deep_agent import Gateway, ScriptedModel, call, final


IDEOGRAM = "ideogram/v4.5/edit"
RECRAFT = "fal-ai/recraft/v4.1/pro/text-to-vector"
EDIT = {"prompt": "Replace only SALE with SOLD, preserve everything else", "image_url": "https://example.com/source.png"}
VECTOR = {"prompt": "An editable SVG fox logo"}
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><defs><linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient></defs><path d="M0 0L10 10" fill="url(#g)"/></svg>'
UNSAFE_SVG = SVG.replace(b'<path ', b'<script>alert(1)</script><foreignObject><div>bad</div></foreignObject><image href="https://example.com/tracker"/><style>@import url(https://example.com/a)</style><animate attributeName="href" values="javascript:alert(1)"/><path onload="alert(1)" style="fill:url(https://example.com/x)" ')
PNG = b'\x89PNG\r\n\x1a\n' + b'fake-image-bytes'


class ImageSpecialistProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        env = patch.dict(os.environ, {"FAL_DRY_RUN": "true", "RENDERHAUS_MEDIA_DIR": str(self.root),
                                    "AWS_S3_BUCKET": "", "REMOTION_APP_BUCKET_NAME": "", "AWS_LAMBDA_FUNCTION_NAME": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_schema_exposes_verified_arguments_and_defaults(self):
        schemas = {s["name"]: s["inputSchema"] for s in generate_schemas(get_provider("fal"))}
        self.assertIn("ideogram_edit", schemas)
        self.assertIn("recraft_text_to_vector", schemas)
        self.assertIn("high", schemas["ideogram_edit"]["properties"]["edit_precision"]["description"])
        self.assertIn("1-8", schemas["ideogram_edit"]["properties"]["num_images"]["description"])
        self.assertNotIn("style", schemas["recraft_text_to_vector"]["properties"])

    def test_default_dry_run_and_saved_handle_never_make_http_or_create_artifacts(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(httpx, "Client") as client:
            for tool, args, model in [("ideogram_edit", EDIT, IDEOGRAM), ("recraft_text_to_vector", VECTOR, RECRAFT)]:
                result = dispatch("fal", tool, args)
                self.assertEqual((result["status"], result["model"]), ("dry_run", model))
                self.assertFalse(result["training_eligible"])
                self.assertNotIn("output_path", result)
                with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
                    self.assertEqual(dispatch("fal", "get_video_task", {"job_id": result["job_id"], "download": True})["status"], "dry_run")
            client.assert_not_called()

    def test_invalid_requests_fail_before_paid_http_at_gateway_boundary(self):
        cases = [("ideogram_edit", EDIT, invalid) for invalid in [
            {"image_url": "file:///etc/passwd"}, {"image_url": "http://example.com/a.png"},
            {"image_url": "https://user:secret@example.com/a.png"}, {"image_url": "https://127.0.0.1/a.png"},
            {"prompt": " "}, {"prompt": "x" * 10001}, {"quality": "ultra"}, {"quality": None},
            {"num_images": True}, {"num_images": 0}, {"num_images": 9}, {"num_images": 1.5},
            {"reference_image_urls": [EDIT["image_url"]] * 5},
            {"reference_image_urls": [EDIT["image_url"]] * 4, "mask_url": EDIT["image_url"]},
            {"mask_url": ""}, {"mask_url": "javascript:alert(1)"}, {"edit_precision": "high", "image_size": "square"},
            {"edit_precision": "regular", "mask_url": EDIT["image_url"], "image_size": "square"},
            {"edit_precision": "regular", "image_size": {"width": 257, "height": 512}},
            {"edit_precision": "regular", "image_size": {"width": 4096, "height": 4096}},
            {"edit_precision": "regular", "image_size": {"width": 2048, "height": 256}},
            {"seed": True}, {"sync_mode": True}, {"model": "unknown"},
        ]] + [("recraft_text_to_vector", VECTOR, invalid) for invalid in [
            {"style": "vector_illustration"}, {"num_images": 2}, {"prompt": " "}, {"prompt": "x" * 10001},
            {"image_size": {"width": True, "height": 512}}, {"image_size": {"width": 14143, "height": 512}},
            {"colors": [{"r": 256, "g": 0, "b": 0}]}, {"colors": [{"r": True, "g": 0, "b": 0}]},
            {"background_color": {"r": 0, "g": 0, "b": 0, "extra": 1}}, {"enable_safety_checker": "true"},
        ]]
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
            for tool, args, invalid in cases:
                with self.subTest(tool=tool, invalid=invalid), self.assertRaises(ValueError):
                    dispatch("fal", tool, {**args, **invalid})
            client.assert_not_called()

    def test_mask_reference_limits_and_geometry_controls(self):
        preview = dispatch("fal", "ideogram_edit", {**EDIT, "mask_url": EDIT["image_url"],
            "reference_image_urls": [EDIT["image_url"]] * 3, "quality": "high"})
        self.assertEqual(preview["request_preview"]["edit_precision"], "high")
        self.assertEqual(preview["request_preview"]["image_size"], "auto")
        resized = dispatch("fal", "ideogram_edit", {**EDIT, "edit_precision": "regular", "image_size": "square"})
        self.assertEqual(resized["request_preview"]["image_size"], "square")

    def test_mock_http_submission_uses_verified_endpoints_and_payloads(self):
        for tool, args, endpoint in [("ideogram_edit", EDIT, IDEOGRAM), ("recraft_text_to_vector", VECTOR, RECRAFT)]:
            requests = []
            def respond(request):
                requests.append(request)
                return httpx.Response(200, json={"request_id": "image-1", "status": "IN_QUEUE"})
            client = httpx.Client(transport=httpx.MockTransport(respond))
            with self.subTest(tool=tool), patch.dict(os.environ, {"FAL_DRY_RUN": "false", "FAL_KEY": "fake"}), patch.object(httpx, "Client", return_value=client):
                result = dispatch("fal", tool, args)
            self.assertEqual(str(requests[0].url), "https://queue.fal.run/" + endpoint)
            self.assertEqual(result["job_id"], endpoint + ":image-1")
            body = json.loads(requests[0].content)
            self.assertEqual(body["prompt"], args["prompt"])
            self.assertNotIn("model", body)
            if tool == "ideogram_edit":
                self.assertEqual(body["edit_precision"], "high")
                self.assertEqual(body["image_url"], args["image_url"])
            else:
                self.assertEqual(body["image_size"], "square_hd")
                self.assertNotIn("style", body)

    def test_unresolved_studio_handles_preview_but_never_submit_live(self):
        args = {**EDIT, "image_url": "renderhaus-asset://source", "mask_url": "renderhaus-asset://mask"}
        self.assertEqual(dispatch("fal", "ideogram_edit", args)["status"], "dry_run")
        self.assertIsNotNone(routing.estimate_cost("Fal___ideogram_edit", args).total_cents)
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
            with self.assertRaisesRegex(ValueError, "resolve"):
                dispatch("fal", "ideogram_edit", args)
            client.assert_not_called()

    def poll(self, endpoint, images, *, download=True, content=SVG, mime="image/svg+xml"):
        def respond(request):
            if str(request.url).endswith("/status"):
                return httpx.Response(200, json={"status": "COMPLETED"})
            if request.url.host == "queue.fal.run":
                return httpx.Response(200, json={"images": images, "seed": 42})
            return httpx.Response(200, content=content, headers={"content-type": mime})
        original_client = httpx.Client
        def client(*args, **kwargs):
            return original_client(*args, transport=httpx.MockTransport(respond), **kwargs)
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false", "FAL_KEY": "fake"}), patch.object(httpx, "Client", side_effect=client):
            return dispatch("fal", "get_video_task", {"job_id": endpoint + ":image-1", "download": download})

    def test_vector_poll_always_sanitizes_every_svg_and_never_exposes_vendor_url(self):
        outputs = [{"url": f"https://example.com/{n}.svg", "content_type": "image/svg+xml"} for n in range(2)]
        result = self.poll(RECRAFT, outputs, download=False, content=UNSAFE_SVG)
        self.assertEqual((result["status"], len(result["images"])), ("succeeded", 2))
        self.assertFalse(result["training_eligible"])
        self.assertNotIn("https://example.com", json.dumps(result))
        for image in result["images"]:
            data = Path(image["output_path"]).read_bytes()
            self.assertIn(b'viewBox="0 0 10 10"', data)
            self.assertIn(b'fill="url(#g)"', data)
            for unsafe in (b"script", b"foreignObject", b"onload", b"style=", b"https://", b"animate"):
                self.assertNotIn(unsafe, data)
        self.assertEqual(result["output_path"], result["images"][0]["output_path"])

    def test_svg_rejects_mime_mismatch_xml_entities_and_non_svg_without_persisting(self):
        for images, content, mime in [
            ([{"url": "https://example.com/a.svg", "content_type": "image/png"}], SVG, "image/svg+xml"),
            ([{"url": "https://example.com/a.svg", "content_type": "image/svg+xml"}], SVG, "text/html"),
            ([{"url": "https://example.com/a.svg", "content_type": "image/svg+xml"}], b'<!DOCTYPE svg [<!ENTITY x "bad">]><svg>&x;</svg>', "image/svg+xml"),
            ([{"url": "https://example.com/a.svg", "content_type": "image/svg+xml"}], b"<html>bad</html>", "image/svg+xml"),
            ([{"url": "file:///etc/passwd", "content_type": "image/svg+xml"}], SVG, "image/svg+xml"),
            ([], SVG, "image/svg+xml"),
        ]:
            with self.subTest(images=images, mime=mime), self.assertRaises((RuntimeError, ValueError)):
                self.poll(RECRAFT, images, content=content, mime=mime)
            self.assertFalse(list(self.root.rglob("*.svg")))

    def test_raster_poll_persists_multiple_images_and_missing_results_are_errors(self):
        outputs = [{"url": f"https://example.com/{n}.png", "content_type": "image/png"} for n in range(2)]
        result = self.poll(IDEOGRAM, outputs, content=PNG, mime="image/png")
        self.assertEqual(len(result["images"]), 2)
        self.assertTrue(all(Path(image["output_path"]).read_bytes() == PNG for image in result["images"]))

    def test_lambda_requires_durable_svg_output_before_paid_submit(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false", "AWS_LAMBDA_FUNCTION_NAME": "image-worker"}), patch.object(httpx, "Client") as client:
            with self.assertRaisesRegex(RuntimeError, "AWS_S3_BUCKET"):
                dispatch("fal", "recraft_text_to_vector", VECTOR)
            client.assert_not_called()

    def test_s3_publishes_sanitized_svg_bytes_and_no_worker_path(self):
        s3 = Mock()
        s3.generate_presigned_url.return_value = "https://example.test/sanitized.svg"
        with patch.dict(os.environ, {"AWS_S3_BUCKET": "image-bucket"}), patch("boto3.client", return_value=s3):
            result = self.poll(RECRAFT, [{"url": "https://example.com/raw.svg", "content_type": "image/svg+xml"}], content=UNSAFE_SVG)
        self.assertEqual(result["image_url"], "https://example.test/sanitized.svg")
        self.assertNotIn("output_path", result)
        self.assertNotIn(b"script", s3.put_object.call_args.kwargs["Body"])
        self.assertEqual(s3.put_object.call_args.kwargs["ContentType"], "image/svg+xml")


class ImageSpecialistPolicyTests(unittest.TestCase):
    def test_exception_default_and_explicit_precedence(self):
        for prompt, alias in [
            ("editable SVG logo", "recraft_v41_vector"), ("fix the typo in this banner", "ideogram45_edit"),
            ("replace only the headline on this existing image", "ideogram45_edit"),
            ("change the text only on this image", "ideogram45_edit"),
            ("GPT Image 2.5 edit this image and fix the typo", "gpt_image25_edit"),
            ("use Ideogram to edit this image", "ideogram45_edit"),
            ("use Recraft for an icon", "recraft_v41_vector"),
            ("generate a poster with text", "gpt_image25_t2i"),
            ("generate a text-only poster", "gpt_image25_t2i"),
        ]:
            for confidential in (False, True):
                with self.subTest(prompt=prompt, confidential=confidential):
                    route = routing.route_intent(prompt, confidential=confidential)
                    self.assertEqual((route.alias, route.status), (alias, "ready"))
        self.assertEqual(routing.route_intent("edit this image and fix the typo").tool, "Fal___ideogram_edit")
        self.assertIn("A/B", routing.route_intent("fix the typo in this banner").disclosure)
        self.assertFalse(routing.intent_constraints("fix a typo")['predicates']['text_only_edit'])

    def test_existing_image_handle_supports_text_only_predicate(self):
        route = routing.route_intent("change only the text", arguments={"image_url": "renderhaus-asset://source"})
        self.assertEqual(route.tool, "Fal___ideogram_edit")

    def test_preservation_instructions_do_not_count_as_mixed_visual_changes(self):
        for prompt in ("Fix the typo in this image but do not change the background",
                       "Replace only the text on this image; do not edit lighting or composition",
                       "Change only the headline in this poster, don't change the product"):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).tool, "Fal___ideogram_edit")

    def test_mixed_new_and_negated_edits_do_not_take_text_only_exception(self):
        for prompt in ("fix the typo in this image and change the background", "do not fix the typo, edit this image lighting", "generate a new poster and fix a typo"):
            with self.subTest(prompt=prompt):
                self.assertFalse(routing.intent_constraints(prompt)["predicates"]["text_only_edit"])
        route = routing.route_intent("use GPT Image 2.5 for an editable SVG logo")
        self.assertEqual(route.status, "blocked")
        self.assertIn("vector", route.reason.lower())

    def test_mixed_visual_verbs_and_excluded_specialists(self):
        for change in ("make the background blue", "remove that person", "change the entire background",
                       "crop it square", "add a logo"):
            prompt = "Fix the typo in this image and " + change
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).tool, "OpenAI___edit_image")
        for prompt in ("Do not use Ideogram; edit this image and remove the background person",
                       "Do not use Recraft; generate a raster logo"):
            with self.subTest(prompt=prompt):
                self.assertTrue(routing.route_intent(prompt).tool.startswith("OpenAI___"))
        self.assertEqual(routing.route_intent("Do not use Recraft; make an editable SVG logo").status, "blocked")
        self.assertEqual(routing.route_intent("Do not use Ideogram; fix the typo in this image").status, "blocked")

    def test_quoted_text_and_placement_preservation_do_not_select_models(self):
        for prompt in ('Fix the typo in this banner; replace "Recraf" with "Recraft"',
                       'Only change the text on this image',
                       'Fix the typo in this image; do not change the text placement'):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).tool, "Fal___ideogram_edit")
        self.assertEqual(routing.route_intent('Use Ideogram to generate a poster with the headline "fix a typo"').tool,
                         "OpenAI___generate_image")

    def test_graphic_text_edits_keep_remotion_modality(self):
        for prompt in ("Change the text in this Remotion title card", "Edit the text in this motion graphic"):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).alias, "remotion_render")

    def test_quoted_dialogue_still_uses_seedance_exception(self):
        route = routing.route_intent('Generate a video of a fictional fox: "Hello there"')
        self.assertEqual(route.alias, "seedance25_t2v")

    def test_vector_headline_generation_and_whiteboard_keep_their_modality(self):
        for prompt in ('Generate an editable SVG logo with headline',
                       'Generate an editable SVG with the headline "edit text"'):
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).tool, "Fal___recraft_text_to_vector")
        self.assertEqual(routing.route_intent("whiteboard explainer").skill, "whiteboard-explainer")
        self.assertEqual(routing.route_intent("Change the text in this Remotion title card").skill, "motion-graphics")

    def test_image_approval_rules_and_official_cost_quotes(self):
        for tool, args, provider_cents in [("ideogram_edit", {**EDIT, "quality": "low", "num_images": 2}, 6),
                                         ("ideogram_edit", {**EDIT, "quality": "medium"}, 6),
                                         ("ideogram_edit", {**EDIT, "quality": "high"}, 22),
                                         ("ideogram_edit", {**EDIT, "quality": "very_low"}, 1),
                                         ("recraft_text_to_vector", VECTOR, 30)]:
            name = "Fal___" + tool
            self.assertTrue(tool_needs_approval(name, False))
            self.assertFalse(tool_needs_approval(name, True))
            with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
                self.assertEqual(cost_for("fal", tool, args).total_cents, 0)
                self.assertGreater(routing.estimate_cost(name, args).total_cents, 0)
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
                self.assertEqual(cost_for("fal", tool, args).provider_cents, provider_cents)
        for alias in ("ideogram45_edit", "recraft_v41_vector"):
            policy = routing.POLICY["model_policies"][alias]
            self.assertFalse(policy["training_eligible"])
            self.assertEqual(policy["license"], "service-terms")

    def test_studio_ingestion_sanitizes_local_remote_and_data_svg(self):
        from server import studio
        from server.studio_state import StudioRepository
        import base64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = StudioRepository(root / "db.sqlite3", root / "stored")
            repo.create_project("workspace", "user", "Vectors", project_id="project")
            source = root / "unsafe.svg"
            source.write_bytes(UNSAFE_SVG)
            for value in (str(source), "data:image/svg+xml;base64," + base64.b64encode(UNSAFE_SVG).decode()):
                ref = repo.register_source(workspace_id="workspace", project_id="project", user_id="user", source=value, kind="image", training_eligible=False)
                self.assertEqual(ref.mime_type, "image/svg+xml")
                self.assertNotIn(b"script", repo.version_path("workspace", ref.version_id).read_bytes())
            remote = "https://example.com/vector.svg"
            response = httpx.Response(200, content=UNSAFE_SVG, headers={"content-type": "image/svg+xml"},
                                      request=httpx.Request("GET", remote))
            with patch.object(httpx, "stream", return_value=nullcontext(response)):
                ref = repo.register_source(workspace_id="workspace", project_id="project", user_id="user", source=remote,
                                           kind="image", training_eligible=False)
                self.assertNotIn(b"script", repo.version_path("workspace", ref.version_id).read_bytes())
            mislabeled = httpx.Response(200, content=UNSAFE_SVG, headers={"content-type": "text/html"},
                                        request=httpx.Request("GET", remote))
            with patch.object(httpx, "stream", return_value=nullcontext(mislabeled)), self.assertRaisesRegex(ValueError, "content-type"):
                repo.register_source(workspace_id="workspace", project_id="project", user_id="user", source=remote, kind="image")
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": directory}):
                assets = studio.collect_asset_sources({"output_path": str(source)})
                self.assertEqual(assets[0]["kind"], "image")


class ImageSpecialistApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_and_context_use_attached_image_for_text_only_edits(self):
        from agent.deep_agent.runner import run_with_servers
        from langchain_core.messages import HumanMessage, ToolMessage

        request = StudioAgentRequest(prompt="change only the text", nodes=[StudioNode(
            id="image", title="Approved poster", kind="image", version_id="image_123")])

        def observe(messages, tools):
            proposal = next(message.content for message in messages if isinstance(message, HumanMessage))
            self.assertIn("Fal___ideogram_edit", proposal)
            context = next(json.loads(message.content) for message in messages
                           if isinstance(message, ToolMessage) and message.name == "read_studio_context")
            self.assertEqual(context["intent_route"]["tool"], "Fal___ideogram_edit")
            return final()

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            await run_with_servers(request, _context_from_request(request), [Gateway()], model=ScriptedModel([
                call("read_studio_context", {}, "context"), observe]))

    async def test_native_cost_pause_reject_and_approve_do_not_double_submit(self):
        from agent.deep_agent.runner import run_with_servers
        for tool, args, prompt in [("ideogram_edit", EDIT, "fix the typo in this image"),
                                   ("recraft_text_to_vector", VECTOR, "make an editable SVG logo")]:
            schemas = generate_schemas(get_provider("fal"))
            name = "Fal___" + tool
            for decision in ("approve", "reject"):
                gateway = Gateway([Tool(name="Fal___" + s["name"], description=s["description"], inputSchema=s["inputSchema"]) for s in schemas], result={"status": "dry_run"})
                request = StudioAgentRequest(prompt=prompt, autonomous=False, job_id=tool + decision)
                studio = _context_from_request(request)
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory, "FAL_DRY_RUN": "true"}):
                    with self.subTest(tool=tool, decision=decision), self.assertRaises(StudioAgentApprovalRequired) as paused:
                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call("read_file", {"file_path": "/skills/image-gen/SKILL.md"}, "skill"),
                            call("call_media_tool", {"tool_name": name, "arguments": args}, "image")]))
                    approval = paused.exception.approvals[0]
                    self.assertIn("Estimated cost $", approval.description)
                    gateway.call_tool.assert_not_awaited()
                    resumed = request.model_copy(update={"session_items": studio.session_items, "resume_state": paused.exception.state,
                        "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                    await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                    if decision == "approve":
                        gateway.call_tool.assert_awaited_once_with(name, args)
                        records = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                        if tool == "ideogram_edit":
                            self.assertEqual(records[-1]["ab_arm"], "ideogram45_edit")
                    else:
                        gateway.call_tool.assert_not_awaited()
