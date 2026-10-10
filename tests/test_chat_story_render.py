from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch


def sample_story() -> dict:
    return {
        "payload": {
            "theme": "generic", "aspect": "9:16", "sfx": True,
            "contact": {"name": "Avery", "avatar": "initials"},
            "dramatization": True,
            "messages": [
                {"from": "me", "text": "Are you coming?", "status": "read", "reaction": ""},
                {"from": "them", "text": "On my way!", "status": "", "reaction": "❤️"},
            ],
        },
        "plan": {
            "fps": 20, "width": 320, "height": 568, "durationInFrames": 80,
            "safeTop": 80, "safeBottom": 90,
            "fontSize": 12, "lineHeight": 16, "padding": 10,
            "bubbles": [
                {"index": 0, "typingStartFrame": None, "startFrame": 12,
                 "reactionFrame": None, "receiptFrame": 26,
                 "lines": ["Are you coming?"], "x": 130, "y": 100,
                 "width": 170, "height": 42, "scrollOffset": 0, "tail": True},
                {"index": 1, "typingStartFrame": 40, "startFrame": 54,
                 "reactionFrame": 62, "receiptFrame": None,
                 "lines": ["On my way!"], "x": 20, "y": 420,
                 "width": 150, "height": 42, "scrollOffset": 80, "tail": True},
            ],
            "scrollEvents": [{"frame": 40, "endFrame": 54, "offset": 80}],
            "sfxCues": [{"frame": 12, "kind": "send"}, {"frame": 54, "kind": "receive"}],
            "warnings": [],
        },
    }


class ChatStoryFrameTests(unittest.TestCase):
    def renderer(self):
        from providers.remotion import chat_story_render
        return chat_story_render

    def test_measured_text_width_refuses_clipping(self):
        renderer = self.renderer()
        story = sample_story()
        story['plan']['bubbles'][0]['lines'] = ['W' * 30]
        with self.assertRaisesRegex(ValueError, 'width'):
            renderer.draw_chat_frame(story, 30)

    def test_unsupported_joined_emoji_refuses_instead_of_cropping(self):
        renderer = self.renderer()
        story = sample_story()
        story['plan']['bubbles'][0]['lines'] = ['👩\u200d👩\u200d👩']
        with self.assertRaisesRegex(ValueError, 'joined emoji'):
            renderer.draw_chat_frame(story, 30)

    def test_drip_reveal_sent_right_received_left(self):
        renderer = self.renderer()
        story = sample_story()
        before = renderer.draw_chat_frame(story, 0)
        sent = renderer.draw_chat_frame(story, 20)
        received = renderer.draw_chat_frame(story, 70)
        self.assertEqual(before.size, (320, 568))
        self.assertEqual(before.getpixel((285, 110)), before.getpixel((40, 110)))
        self.assertNotEqual(sent.getpixel((285, 110)), sent.getpixel((40, 110)))
        self.assertNotEqual(received.getpixel((30, 350)), before.getpixel((30, 350)))
        self.assertEqual(story, sample_story(), "Drawing must not mutate the approved payload.")

    def test_typing_precedes_received_bubble_and_finishes_on_reveal(self):
        renderer = self.renderer()
        story = sample_story()
        waiting = renderer.draw_chat_frame(story, 46)
        previous = renderer.draw_chat_frame(story, 39)
        reply = renderer.draw_chat_frame(story, 70)
        self.assertNotEqual(waiting.crop((15, 300, 180, 478)).tobytes(),
                            previous.crop((15, 300, 180, 478)).tobytes())
        self.assertNotEqual(waiting.crop((15, 300, 180, 478)).tobytes(),
                            reply.crop((15, 300, 180, 478)).tobytes())

    def test_scroll_settles_at_reveal_and_viewport_protects_safe_zone(self):
        renderer = self.renderer()
        story = sample_story()
        self.assertEqual(renderer.scroll_offset(story["plan"], 39), 0)
        self.assertGreater(renderer.scroll_offset(story["plan"], 46), 0)
        self.assertLess(renderer.scroll_offset(story["plan"], 46), 80)
        self.assertEqual(renderer.scroll_offset(story["plan"], 54), 80)
        clean = renderer.draw_chat_frame(story, 0)
        final = renderer.draw_chat_frame(story, 79)
        self.assertEqual(clean.crop((0, 478, 320, 568)).tobytes(),
                         final.crop((0, 478, 320, 568)).tobytes())

    def test_reaction_appears_after_its_bubble(self):
        renderer = self.renderer()
        story = sample_story()
        before = renderer.draw_chat_frame(story, 61)
        after = renderer.draw_chat_frame(story, 70)
        self.assertNotEqual(before.crop((15, 360, 180, 400)).tobytes(),
                            after.crop((15, 360, 180, 400)).tobytes())

    def test_verbatim_unicode_and_markup_remain_literal_text(self):
        renderer = self.renderer()
        story = sample_story()
        story["payload"]["messages"][0]["text"] = "<b>Hello 😀</b>"
        story["plan"]["bubbles"][0]["lines"] = ["<b>Hello 😀</b>"]
        original = copy.deepcopy(story)
        image = renderer.draw_chat_frame(story, 30)
        self.assertEqual(image.size, (320, 568))
        self.assertEqual(story, original)
        self.assertNotEqual(image.crop((130, 100, 300, 145)).tobytes(),
                            renderer.draw_chat_frame(sample_story(), 30).crop((130, 100, 300, 145)).tobytes())

    def test_sent_reaction_leaves_the_read_receipt_visible(self):
        renderer = self.renderer()
        story = sample_story()
        story["payload"]["messages"][0]["reaction"] = "👍"
        story["plan"]["bubbles"][0]["reactionFrame"] = 30
        before = renderer.draw_chat_frame(story, 29)
        after = renderer.draw_chat_frame(story, 35)
        self.assertEqual(before.crop((278, 142, 302, 158)).tobytes(),
                         after.crop((278, 142, 302, 158)).tobytes(),
                         "A reaction must not replace pixels in the receipt.")
        self.assertNotEqual(before.crop((130, 140, 160, 160)).tobytes(),
                            after.crop((130, 140, 160, 160)).tobytes())

    def test_keycaps_and_tagged_flags_use_complete_color_glyphs(self):
        from PIL import Image
        renderer = self.renderer()
        england = "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"
        for text in ("1️⃣", england):
            with self.subTest(text=text):
                self.assertEqual(renderer._runs(text), [(text, True)])
                image = Image.new("RGBA", (100, 70))
                renderer._text(image, text, (4, 4), size=38, fill="#ffffff")
                colors = {pixel[:3] for pixel in image.get_flattened_data() if pixel[3] > 150}
                self.assertTrue(any(max(color) - min(color) > 30 for color in colors),
                                "The full emoji must produce a visible color glyph.")
        with patch.object(renderer, "EMOJI_FONT", Path("/missing/NotoColorEmoji.ttf")):
            with self.assertRaisesRegex(ValueError, "emoji font"):
                renderer._text(Image.new("RGBA", (100, 70)), "1️⃣", (4, 4), size=38, fill="#ffffff")

    def test_mixed_direction_with_emoji_refuses_instead_of_reordering_words(self):
        renderer = self.renderer()
        story = sample_story()
        for text in ("שלום A😊B", "Aשלום😊B", "שלום 1😊2"):
            with self.subTest(text=text):
                story["payload"]["messages"][0]["text"] = text
                story["plan"]["bubbles"][0]["lines"] = [text]
                with self.assertRaisesRegex(ValueError, "mixed.*direction.*emoji"):
                    renderer.draw_chat_frame(story, 30)
        story["payload"]["messages"][0]["text"] = "שלום 😊"
        story["plan"]["bubbles"][0]["lines"] = ["שלום 😊"]
        self.assertEqual(renderer.draw_chat_frame(story, 30).size, (320, 568))

    def test_header_uses_the_bounded_contact_font_in_the_plan(self):
        renderer = self.renderer()
        story = sample_story()
        story["payload"]["contact"]["name"] = "W" * 20
        story["plan"]["contactFontSize"] = 8
        observed = []
        original = renderer._text

        def draw_text(image, text, xy, **kwargs):
            if text == story["payload"]["contact"]["name"]:
                observed.append((xy, kwargs["size"]))
            return original(image, text, xy, **kwargs)

        with patch.object(renderer, "_text", side_effect=draw_text):
            renderer.draw_chat_frame(story, 20)
        self.assertEqual(observed[0][1], 8)
        self.assertGreaterEqual(observed[0][0][0], 48 * 320 / 1080)

    def test_header_refuses_a_name_that_still_exceeds_its_safe_width(self):
        story = sample_story()
        story["payload"]["contact"]["name"] = "W" * 40
        with self.assertRaisesRegex(ValueError, "bounded header"):
            self.renderer().draw_chat_frame(story, 0)

    def test_square_dramatization_label_stays_clear_of_the_contact(self):
        renderer = self.renderer()
        story = sample_story()
        story["plan"].update(width=1080, height=1080, safeTop=190, safeBottom=130)
        labels = {}
        original = renderer._text

        def draw_text(image, text, xy, **kwargs):
            if text in {"Dramatization", "Avery"}:
                labels[text] = (xy[1], kwargs["size"])
            return original(image, text, xy, **kwargs)

        with patch.object(renderer, "_text", side_effect=draw_text):
            renderer.draw_chat_frame(story, 0)
        self.assertLessEqual(sum(labels["Dramatization"]), labels["Avery"][0])

    def test_missing_emoji_font_refuses_instead_of_silent_tofu(self):
        renderer = self.renderer()
        with patch.object(renderer, "EMOJI_FONT", Path("/missing/NotoColorEmoji.ttf")):
            with self.assertRaisesRegex(ValueError, "emoji font"):
                renderer.draw_chat_frame(sample_story(), 70)

    def test_synthesized_pop_is_short_pcm_without_external_audio(self):
        renderer = self.renderer()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "send.wav"
            renderer.write_pop(path, "send")
            with wave.open(str(path), "rb") as stream:
                self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate()),
                                 (1, 2, 48000))
                self.assertAlmostEqual(stream.getnframes() / stream.getframerate(), .12, places=4)
                self.assertNotEqual(set(stream.readframes(stream.getnframes())), {0})

    def test_submit_queues_the_story_without_rendering_frames(self):
        from providers.remotion import local
        story = sample_story()
        props = {"document": {"id": "chat", "name": "Chat", "assets": [], "tracks": [],
                              "chatStory": story},
                 "renderConfig": {**{key: story["plan"][key] for key in
                                      ("fps", "width", "height", "durationInFrames")},
                                  "videoBitrate": None, "crf": 18,
                                  "resolution": {"width": 320, "height": 568,
                                                 "source_resolution": "320x568", "upscaled": False, "warnings": []}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = Mock(pid=123)
            with patch.object(local, "validate_document"), patch.object(local, "_command") as command, \
                    patch.object(local.subprocess, "Popen", return_value=process):
                result = local.start_render(props, output_filename="chat.mp4",
                                            media_roots=(root,), source_root=root)
            self.addCleanup(local._PROCESSES.pop, result["render_id"], None)
            self.assertEqual(result["status"], "queued")
            command.assert_not_called()
            state = json.loads((root / "remotion/local" / result["render_id"] / "worker.json").read_text())
            self.assertEqual(state["props"]["document"]["chatStory"], story)
            self.assertNotIn("command", state)

    def test_worker_records_a_preparation_failure_for_polling(self):
        from providers.remotion import local, local_worker
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "worker.json").write_text(json.dumps({
                "props": {"document": {"chatStory": sample_story()}}, "media_roots": [temporary],
                "source_root": temporary, "filename": "chat.mp4", "timeout": 10,
            }))
            with patch.object(local, "_command", side_effect=ValueError("The emoji font is missing.")):
                local_worker.run(directory)
            result = json.loads((directory / "terminal.json").read_text())
            self.assertIn("emoji font", result["error"])
            self.assertIsNone(result["exit_code"])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class ChatStoryBinaryTests(unittest.TestCase):
    def test_real_silent_visual_has_plan_dimensions_duration_and_cfr(self):
        from providers.remotion.chat_story_render import render_chat_visual
        with tempfile.TemporaryDirectory() as temporary:
            result = render_chat_visual(sample_story(), Path(temporary))
            inspected = subprocess.run([
                "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                result["visual_path"],
            ], check=True, capture_output=True, timeout=20)
            probe = json.loads(inspected.stdout)
            video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (320, 568))
            self.assertEqual(video["avg_frame_rate"], "20/1")
            self.assertAlmostEqual(float(probe["format"]["duration"]), 4, delta=1 / 20)
            self.assertEqual(int(video["nb_frames"]), 80)
            self.assertFalse(any(stream["codec_type"] == "audio" for stream in probe["streams"]))
            self.assertTrue(Path(result["send_path"]).is_file())
            self.assertTrue(Path(result["receive_path"]).is_file())

    def test_sfx_off_creates_no_audio_assets(self):
        from providers.remotion.chat_story_render import render_chat_visual
        story = sample_story()
        story["payload"]["sfx"] = False
        with tempfile.TemporaryDirectory() as temporary:
            result = render_chat_visual(story, Path(temporary))
            self.assertIsNone(result["send_path"])
            self.assertIsNone(result["receive_path"])

    def test_existing_timeline_mixer_places_pop_audio_at_the_bubble_frame(self):
        from providers.ffmpeg.api import _bounded_run
        from providers.remotion import local
        story = sample_story()
        props = {"document": {"id": "chat", "name": "Chat", "assets": [], "tracks": [], "chatStory": story},
                 "renderConfig": {"fps": 20, "width": 320, "height": 568,
                                  "durationInFrames": 80, "videoBitrate": None, "crf": 18}}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normal = local._chat_timeline(props, directory)
            command, duration = local._command(normal, directory, media_roots=(directory,),
                                                source_root=directory, filename="chat.mp4")
            self.assertEqual(duration, 4)
            result = _bounded_run(command, directory, 30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            audio = subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(directory / "chat.mp4"),
                "-map", "0:a", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1",
            ], check=True, capture_output=True, timeout=20).stdout
            import struct
            samples = struct.unpack('<' + 'h' * (len(audio) // 2), audio)
            self.assertLess(max(abs(value) for value in samples[:round(.45 * 48000)]), 10)
            self.assertGreater(max(abs(value) for value in samples[round(.6 * 48000):round(.72 * 48000)]), 500)
            self.assertEqual(props["document"]["tracks"], [], "The approved document must remain unchanged.")
