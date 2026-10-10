from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import tomllib
import unittest
from fnmatch import fnmatch
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from agent.hyperframes import HYPERFRAMES_TOOL, HyperFramesServer

ROOT = Path(__file__).resolve().parents[1]
SKILL = files("agent.deep_agent").joinpath("skills/hyperframes")
PREVIEW_ENV = {"HYPERFRAMES_ENABLED": "true", "HYPERFRAMES_DRY_RUN": "true"}


class CompositionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.stack = []
        self.scripts = []
        self.styles = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs), tuple(self.stack)))
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - self.stack[::-1].index(tag) - 1]

    def handle_data(self, data):
        if self.stack and self.stack[-1] == "script":
            self.scripts.append(data)
        if self.stack and self.stack[-1] == "style":
            self.styles.append(data)


class HyperFramesPackTests(unittest.IsolatedAsyncioTestCase):
    def catalog(self):
        path = SKILL.joinpath("templates/catalog.json")
        self.assertTrue(path.is_file(), "The existing HyperFrames skill must package its template catalog.")
        catalog = json.loads(path.read_text())
        self.assertEqual(set(catalog), {
            "cinematic-caption", "tactile-collage", "hyfrme-text-motion",
            "hyfrme-transitions", "hyfrme-product-demo",
        })
        return catalog

    def arguments(self, entry):
        filename = entry["html_file"]
        self.assertEqual(Path(filename).name, filename)
        html = SKILL.joinpath("templates", filename).read_text()
        return {**entry["arguments"], "html": html}

    def test_pack_roots_and_clips_have_matching_bounded_envelopes(self):
        for name, entry in self.catalog().items():
            with self.subTest(pack=name):
                arguments = self.arguments(entry)
                parsed = CompositionParser()
                parsed.feed(arguments["html"])
                roots = [(attrs, parents) for _, attrs, parents in parsed.elements
                         if "data-composition-id" in attrs]
                self.assertEqual(len(roots), 1)
                root, parents = roots[0]
                self.assertEqual(parents[-1], "body")
                self.assertNotIn("template", parents)
                self.assertEqual(float(root["data-duration"]), arguments["duration_seconds"])
                for field in ("width", "height", "fps"):
                    self.assertEqual(int(root[f"data-{field}"]), arguments[field])
                ids = [attrs["id"] for _, attrs, _ in parsed.elements if "id" in attrs]
                self.assertEqual(len(ids), len(set(ids)))
                clips = [attrs for _, attrs, _ in parsed.elements
                         if "clip" in attrs.get("class", "").split()]
                self.assertGreaterEqual(len(clips), 3)
                for clip in clips:
                    self.assertIn("id", clip)
                    start, duration = float(clip["data-start"]), float(clip["data-duration"])
                    self.assertGreaterEqual(start, 0)
                    self.assertGreater(duration, 0)
                    self.assertLessEqual(start + duration, arguments["duration_seconds"])

    def test_templates_register_one_paused_timeline_and_target_inner_elements(self):
        harness = """
const vm = require('node:vm');
const source = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const timelines = [];
const gsap = {timeline(options) {
  const timeline = {options, calls: []};
  for (const method of ['set', 'to', 'from', 'fromTo']) {
    timeline[method] = (...args) => {timeline.calls.push({method, args}); return timeline;};
  }
  timelines.push(timeline);
  return timeline;
}};
const sandbox = {window: {}, gsap};
vm.runInNewContext(source, sandbox, {timeout: 1000});
process.stdout.write(JSON.stringify({timelines, registry: sandbox.window.__timelines}));
"""
        for name, entry in self.catalog().items():
            with self.subTest(pack=name):
                parsed = CompositionParser()
                parsed.feed(self.arguments(entry)["html"])
                result = subprocess.run(["node", "-e", harness], input=json.dumps("\n".join(parsed.scripts)),
                                        capture_output=True, text=True, check=True)
                execution = json.loads(result.stdout)
                self.assertEqual(len(execution["timelines"]), 1)
                timeline = execution["timelines"][0]
                self.assertTrue(timeline["options"]["paused"])
                root = next(attrs for _, attrs, _ in parsed.elements if "data-composition-id" in attrs)
                self.assertEqual(execution["registry"], {root["data-composition-id"]: timeline})
                ids = {attrs["id"]: attrs for _, attrs, _ in parsed.elements if "id" in attrs}
                self.assertTrue(timeline["calls"])
                for call in timeline["calls"]:
                    selector = call["args"][0]
                    self.assertRegex(selector, r"^#[a-z][a-z0-9-]+$")
                    target = ids[selector[1:]]
                    self.assertNotIn("clip", target.get("class", "").split())
                    position = call["args"][-1]
                    self.assertIsInstance(position, (int, float))
                    self.assertGreaterEqual(position, 0)
                    options = call["args"][2 if call["method"] == "fromTo" else 1]
                    self.assertLessEqual(position + options.get("duration", 0), entry["arguments"]["duration_seconds"])

    def test_templates_require_no_downloads_or_remote_assets(self):
        for name, entry in self.catalog().items():
            with self.subTest(pack=name):
                parsed = CompositionParser()
                parsed.feed(self.arguments(entry)["html"])
                for tag, attrs, _ in parsed.elements:
                    self.assertNotIn(tag, {"iframe", "video", "audio", "img", "link", "template"})
                    self.assertNotIn("src", attrs)
                self.assertFalse(re.search(r"url\s*\(|@import|@font-face", "\n".join(parsed.styles)))

    async def test_pack_envelopes_preview_without_executing_html_or_returning_media(self):
        with patch.dict(os.environ, PREVIEW_ENV, clear=True):
            server = HyperFramesServer()
            for name, entry in self.catalog().items():
                with self.subTest(pack=name):
                    result = await server.call_tool(HYPERFRAMES_TOOL.name, self.arguments(entry))
                    self.assertEqual(result["status"], "dry_run")
                    self.assertEqual(result["composition"], entry["arguments"])
                    self.assertFalse({"url", "output_path", "job_id", "render_id", "artifact"} & result.keys())

    async def test_pack_envelopes_fail_closed_when_disabled_or_live(self):
        for env, reason in [({}, "disabled"), ({**PREVIEW_ENV, "HYPERFRAMES_DRY_RUN": "false"}, "isolated renderer")]:
            with patch.dict(os.environ, env, clear=True):
                for name, entry in self.catalog().items():
                    with self.subTest(pack=name, env=env):
                        result = await HyperFramesServer().call_tool(HYPERFRAMES_TOOL.name, self.arguments(entry))
                        self.assertEqual(result["status"], "not_run")
                        self.assertIn(reason, result["reason"].lower())
                        self.assertFalse({"url", "output_path", "job_id", "render_id"} & result.keys())

    async def test_invalid_pack_arguments_are_rejected_before_live_renderer_gate(self):
        with patch.dict(os.environ, {**PREVIEW_ENV, "HYPERFRAMES_DRY_RUN": "false"}, clear=True):
            for name, entry in self.catalog().items():
                for changes in [{"html": ""}, {"duration_seconds": 301}, {"width": True}, {"fps": 0}, {"command": "render"}]:
                    with self.subTest(pack=name, changes=changes):
                        result = await HyperFramesServer().call_tool(HYPERFRAMES_TOOL.name, {**self.arguments(entry), **changes})
                        self.assertEqual(result["status"], "not_run")
                        self.assertIn("schema", result["reason"].lower())

    def test_nested_resources_are_available_through_native_skill_filesystem(self):
        from deepagents.backends import FilesystemBackend

        backend = FilesystemBackend(root_dir=ROOT / "agent/deep_agent/skills", virtual_mode=True)
        resources = ["templates/catalog.json", "references/cinematic-caption.md", "references/tactile-collage.md",
                     "references/hyfrme.md"]
        resources.extend("templates/" + entry["html_file"] for entry in self.catalog().values())
        for resource in resources:
            with self.subTest(resource=resource):
                response = backend.download_files(["/hyperframes/" + resource])[0]
                self.assertIsNone(response.error)
                self.assertEqual(response.content, SKILL.joinpath(resource).read_bytes())

    def test_resource_and_mit_notice_files_are_in_distribution_configuration(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
        patterns = config["package-data"]["agent.deep_agent"]
        for resource in ["references/cinematic-caption.md", "references/tactile-collage.md", "references/hyfrme.md",
                         "templates/catalog.json"] + [
            "templates/" + entry["html_file"] for entry in self.catalog().values()
        ]:
            self.assertTrue(any(fnmatch("skills/hyperframes/" + resource, pattern) for pattern in patterns), resource)
        for name in ("hyperframes-cinematic-caption", "hyperframes-tactile-collage"):
            path = f"third_party/{name}/LICENSE"
            self.assertIn(path, config["license-files"])
            notice = (ROOT / path).read_text()
            self.assertTrue(notice.startswith("MIT License\n\nCopyright (c) 2026 Audrey\n"))
            self.assertIn("Permission is hereby granted, free of charge", notice)
            self.assertIn("THE SOFTWARE IS PROVIDED \"AS IS\"", notice)

    def test_hyfrme_keeps_complete_pinned_mit_notices_and_adaptation_headers(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
        for path, digest in {
            "third_party/hyfrme/LICENSE": "1f9b29bca45562ceb744891478e2dac179a2e3bd1ec5c5d5420abaff8c738eca",
            "third_party/hyfrme/Remocn-LICENSE": "9045ed59114eee12264c0d551288d4ab0f77893c1fc211283410c5c24cc579c6",
        }.items():
            with self.subTest(path=path):
                self.assertIn(path, config["license-files"])
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)
        recipe = SKILL.joinpath("references/hyfrme.md").read_text()
        self.assertIn("26522a993082cd30ad5f404e4890d670c5c73bcb", recipe)
        self.assertIn("PolyForm Shield", recipe)
        for name, entry in self.catalog().items():
            if name.startswith("hyfrme-"):
                html = self.arguments(entry)["html"]
                self.assertIn("Copyright (c) 2026 Akshar Patel", html)
                self.assertIn("third_party/hyfrme/LICENSE", html)
                self.assertIn("Modified by Renderhaus on 2026-10-09", html)
                self.assertIn("26522a993082cd30ad5f404e4890d670c5c73bcb", html)

    def test_hyfrme_samples_use_only_the_host_timeline_dependency(self):
        for name, entry in self.catalog().items():
            if not name.startswith("hyfrme-"):
                continue
            with self.subTest(pack=name):
                parsed = CompositionParser()
                parsed.feed(self.arguments(entry)["html"])
                script = "\n".join(parsed.scripts)
                self.assertNotRegex(script, r"Math\.random|Date\.|performance\.|setTimeout|setInterval|requestAnimationFrame|fetch\(|__hyperframes|__hyfrmeRenderFrame|CustomEase")
                self.assertNotRegex(script, r"\brepeat\s*:")
                self.assertNotIn("data-composition-src", self.arguments(entry)["html"])


class HyperFramesPackRoutingTests(unittest.TestCase):
    def test_hyfrme_patterns_keep_named_only_routing_and_confidential_metadata_inert(self):
        from agent.deep_agent.routing import route_intent

        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for confidential in (True, False):
                    for pattern in ("Hyfrme kinetic titles", "Hyfrme motion graphics transitions",
                                    "Hyfrme motion graphics device card"):
                        for named in (True, False):
                            prompt = pattern + (" with HyperFrames" if named else "")
                            with self.subTest(prompt=prompt, enabled=enabled, confidential=confidential):
                                route = route_intent(prompt, confidential=confidential)
                                self.assertEqual(route.skill, "hyperframes" if named else "motion-graphics")
                                if named and enabled == "false":
                                    self.assertEqual(route.status, "blocked")
                                    self.assertIsNone(route.tool)
                                else:
                                    self.assertEqual(route.status, "ready")
                                    self.assertEqual(route.tool, HYPERFRAMES_TOOL.name if named else "Remotion___render_timeline")

    def test_hyfrme_pack_does_not_implement_product_capture(self):
        from agent.deep_agent.routing import route_intent

        with patch.dict(os.environ, PREVIEW_ENV):
            route = route_intent("Hyfrme motion graphics product UI demo")
            self.assertEqual((route.skill, route.alias, route.status),
                             ("product-demo-video", "cutaway_record", "pending"))
            self.assertIsNone(route.tool)

    def test_caption_styles_keep_motion_routing_with_trailing_instructions(self):
        from agent.deep_agent.routing import route_intent

        for style in ("cinematic captions", "editorial captions"):
            for suffix in ("", "with hero words", "please", "over product footage"):
                prompt = f"Add {style} {suffix}".strip()
                with self.subTest(prompt=prompt):
                    route = route_intent(prompt)
                    self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                     ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_still_output_noun_phrases_preserve_image_generation_with_caption_styles(self):
        from agent.deep_agent.routing import route_intent

        for verb in ("Generate", "Create"):
            for output in ("an image", "images", "an image collage", "a photo collage poster",
                           "a collage image poster", "a photo poster", "a still poster"):
                for style in ("cinematic captions", "editorial captions"):
                    prompt = f"{verb} {output} with {style}"
                    with self.subTest(prompt=prompt):
                        route = route_intent(prompt)
                        self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                         ("image-gen", "gpt_image25_t2i", "OpenAI___generate_image", "ready"))

    def test_motion_output_noun_phrases_preserve_remotion_with_source_clauses(self):
        from agent.deep_agent.routing import route_intent

        for output in ("a photo collage video", "an image collage animation", "an animated photo collage"):
            for source in ("from supplied photos", "using the uploaded image", "with source images"):
                prompt = f"Create {output} {source}"
                with self.subTest(prompt=prompt):
                    route = route_intent(prompt)
                    self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                     ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_compound_photo_collage_output_is_motion(self):
        from agent.deep_agent.routing import route_intent

        prompts = ["Make a photo collage video from the supplied photos",
                   "Create an image collage animation", "Create an animated photo collage"]
        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for confidential in (True, False):
                    for prompt in prompts:
                        with self.subTest(enabled=enabled, confidential=confidential, prompt=prompt):
                            route = route_intent(prompt, confidential=confidential)
                            self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                             ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_html_templates_keep_remotion_without_an_explicit_hyperframes_name(self):
        from agent.deep_agent.routing import route_intent

        prompts = ["use an HTML template for the title card",
                   "use an HTML template for cinematic captions",
                   "use an HTML template for a tactile collage video"]
        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for prompt in prompts:
                    for arguments in (None, {"explicit_hyperframes": True}, {"explicit_html_template": True}):
                        with self.subTest(enabled=enabled, prompt=prompt, arguments=arguments):
                            route = route_intent(prompt, arguments=arguments)
                            self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                             ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_source_images_preserve_caption_and_collage_motion_output(self):
        from agent.deep_agent.routing import route_intent

        prompts = ["Create an animated paper collage using the uploaded photo",
                   "Add cinematic captions to this video with my photo",
                   "Use the still image in an animated collage video",
                   "Make a video collage from these images"]
        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for confidential in (True, False):
                    for prompt in prompts:
                        with self.subTest(enabled=enabled, confidential=confidential, prompt=prompt):
                            route = route_intent(prompt, confidential=confidential)
                            self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                             ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_requested_still_images_with_caption_styling_use_image_generation(self):
        from agent.deep_agent.routing import route_intent

        for prompt in ["Generate images with cinematic captions", "Generate an image with cinematic captions",
                       "Generate a still poster for the collage video"]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.tool),
                                 ("image-gen", "gpt_image25_t2i", "OpenAI___generate_image"))

    def test_unnamed_caption_and_collage_styles_use_remotion_in_every_project(self):
        from agent.deep_agent.routing import route_intent

        prompts = ["premium cinematic captions over product footage", "editorial captions over existing footage",
                   "tactile paper collage video", "animated scrapbook video", "add captions over product footage",
                   "caption this clip", "make an animated paper collage", "make a collage video"]
        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for confidential in (True, False):
                    for prompt in prompts:
                        with self.subTest(enabled=enabled, confidential=confidential, prompt=prompt):
                            route = route_intent(prompt, confidential=confidential)
                            self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                             ("motion-graphics", "remotion_render", "Remotion___render_timeline", "ready"))

    def test_explicit_pack_requests_use_hyperframes_or_block_without_fallback(self):
        from agent.deep_agent.routing import route_intent

        for enabled in ("true", "false"):
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for confidential in (True, False):
                    for prompt in ("HyperFrames cinematic caption over product footage", "HyperFrames tactile collage video",
                                   "HyperFrames animated paper collage using the uploaded photo",
                                   "use an HTML template for the title card with HyperFrames"):
                        with self.subTest(enabled=enabled, confidential=confidential, prompt=prompt):
                            route = route_intent(prompt, confidential=confidential)
                            self.assertEqual(route.skill, "hyperframes")
                            self.assertEqual(route.status, "ready" if enabled == "true" else "blocked")
                            self.assertEqual(route.tool, HYPERFRAMES_TOOL.name if enabled == "true" else None)
                            if enabled == "true":
                                self.assertEqual(route.alias, "hyperframes_render")
                            else:
                                self.assertIn("disabled", route.reason.lower())

    def test_style_requests_preserve_specialized_edits_and_still_images(self):
        from agent.deep_agent.routing import route_intent

        for prompt, skill, alias in [
            ("cut filler ums and add cinematic captions", "conversational-edit", "transcript_edit"),
            ("cut filler ums and add cinematic captions to this video with my photo", "conversational-edit", "transcript_edit"),
            ("generate an image collage poster", "image-gen", "gpt_image25_t2i"),
            ("create a collage image poster", "image-gen", "gpt_image25_t2i"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias), (skill, alias))
