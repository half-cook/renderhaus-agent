from __future__ import annotations

import json
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
        self.assertEqual(set(catalog), {"cinematic-caption", "tactile-collage"})
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
        resources = ["templates/catalog.json", "references/cinematic-caption.md", "references/tactile-collage.md"]
        resources.extend("templates/" + entry["html_file"] for entry in self.catalog().values())
        for resource in resources:
            with self.subTest(resource=resource):
                response = backend.download_files(["/hyperframes/" + resource])[0]
                self.assertIsNone(response.error)
                self.assertEqual(response.content, SKILL.joinpath(resource).read_bytes())

    def test_resource_and_mit_notice_files_are_in_distribution_configuration(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]
        patterns = config["package-data"]["agent.deep_agent"]
        for resource in ["references/cinematic-caption.md", "references/tactile-collage.md", "templates/catalog.json"] + [
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


class HyperFramesPackRoutingTests(unittest.TestCase):
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
                    for prompt in ("HyperFrames cinematic caption over product footage", "HyperFrames tactile collage video"):
                        with self.subTest(enabled=enabled, confidential=confidential, prompt=prompt):
                            route = route_intent(prompt, confidential=confidential)
                            self.assertEqual((route.skill, route.alias), ("hyperframes", "hyperframes_render"))
                            self.assertEqual(route.status, "ready" if enabled == "true" else "blocked")
                            self.assertEqual(route.tool, HYPERFRAMES_TOOL.name if enabled == "true" else None)

    def test_style_requests_preserve_specialized_edits_and_still_images(self):
        from agent.deep_agent.routing import route_intent

        for prompt, skill, alias in [
            ("cut filler ums and add cinematic captions", "conversational-edit", "transcript_edit"),
            ("generate an image collage poster", "image-gen", "gpt_image25_t2i"),
            ("create a collage image poster", "image-gen", "gpt_image25_t2i"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias), (skill, alias))
