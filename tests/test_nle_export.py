from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import opentimelineio as otio

from providers.catalog import get_provider
from providers.nle import build_handoff
from providers.registry import dispatch, generate_schemas, load_committed_schemas
from server.billing_rates import cost_for


GOLDENS = Path(__file__).parent / "golden" / "nle"
MEDIA = GOLDENS / "media"


def snapshot(fps: int | str = 24, drop_frame: bool = False) -> dict:
    separator = ";" if drop_frame else ":"
    assets = []
    for name in ("camera", "generated"):
        assets.append({
            "id": name,
            "name": name.title(),
            "kind": "video",
            "hasAudio": False,
            "url": f"{name}.mp4",
            "versionId": f"version-{name}-1",
            "checksum": hashlib.sha256((MEDIA / f"{name}.mp4").read_bytes()).hexdigest(),
            "sourceTimecode": f"00:00:59{separator}00",
            "reelName": "CAMERA_A_LONG_REEL" if name == "camera" else "GEN_001",
            "provenance": {"origin": "upload"} if name == "camera" else {
                "origin": "generation", "tool": "seedance.image_to_video",
                "source_version_ids": ["version-camera-1"],
            },
            "generated": name == "generated",
            "durationSec": 4,
        })
    return {
        "document": {
            "id": "project-handoff",
            "name": "Editor handoff",
            "assets": assets,
            "tracks": [
                {"id": "camera-track", "name": "Camera", "kind": "video", "items": [
                    {"id": "camera-clip", "type": "clip", "assetId": "camera",
                     "start": 0, "duration": 1, "sourceIn": 1},
                    {"id": "generated-clip", "type": "clip", "assetId": "generated",
                     "start": 1, "duration": 1, "sourceIn": 0},
                ]},
                {"id": "grade-track", "name": "Colourist", "kind": "video", "items": []},
            ],
        },
        "renderConfig": {"fps": fps, "dropFrame": drop_frame,
                         "timecode": f"01:00:00{separator}00", "width": 1920, "height": 1080,
                         "durationInFrames": 60 if drop_frame else int(fps) * 2},
    }


def archive_contents(document: dict) -> dict[str, bytes]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "handoff.zip"
        result = build_handoff(document, path, media_roots=(MEDIA,), source_root=MEDIA)
        assert result["output_path"] == str(path)
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            return {name: archive.read(name) for name in archive.namelist()}


def xml_time(value: str) -> Fraction:
    assert value.endswith("s"), value
    return Fraction(value[:-1])


class NleExportTests(unittest.TestCase):
    def test_otio_round_trip_and_generated_track_isolation(self) -> None:
        original = snapshot()
        before = copy.deepcopy(original)
        contents = archive_contents(original)
        self.assertEqual(original, before)
        timeline = otio.adapters.read_from_string(contents["timeline.otio"].decode(), "otio_json")
        again = otio.adapters.read_from_string(otio.adapters.write_to_string(timeline, "otio_json"), "otio_json")
        self.assertTrue(timeline.is_equivalent_to(again))
        self.assertEqual([track.name for track in timeline.tracks[:2]], ["Camera", "Colourist"])
        camera = list(timeline.tracks[0].find_clips())
        generated = list(timeline.tracks[-1].find_clips())
        self.assertEqual(len(camera), 1)
        self.assertEqual(len(generated), 1)
        self.assertEqual(camera[0].source_range.start_time.value, 60 * 24)
        self.assertEqual(camera[0].media_reference.available_range.start_time.value, 59 * 24)
        self.assertEqual(camera[0].duration().value, 24)
        self.assertEqual(generated[0].range_in_parent().start_time.value, 24)
        metadata = generated[0].metadata["renderhaus"]
        self.assertIn("version-generated-1", str(metadata))
        self.assertIn("version-camera-1", str(metadata))
        self.assertIn("GEN_001", str(metadata))
        self.assertEqual(timeline.global_start_time.value, 3600 * 24)
        for clip in timeline.find_clips():
            self.assertIn(clip.media_reference.target_url, contents)
            self.assertFalse(Path(clip.media_reference.target_url).is_absolute())
        self.assertEqual(json.loads(contents["timeline.otio"]), json.loads((GOLDENS / "timeline.otio").read_text()))

    def test_fcpxml_structure_resources_source_time_and_connected_lanes(self) -> None:
        contents = archive_contents(snapshot())
        root = ET.fromstring(contents["timeline.fcpxml"])
        self.assertEqual(root.tag, "fcpxml")
        resources = root.find("resources")
        ids = [item.attrib["id"] for item in resources]
        self.assertEqual(len(ids), len(set(ids)))
        formats = {item.attrib["id"]: item for item in resources.findall("format")}
        assets = {item.attrib["id"]: item for item in resources.findall("asset")}
        sequence = root.find("./library/event/project/sequence")
        self.assertIn(sequence.attrib["format"], formats)
        self.assertEqual(xml_time(sequence.attrib["tcStart"]), 3600)
        self.assertEqual(xml_time(sequence.attrib["duration"]), 2)
        for asset in assets.values():
            self.assertIn(asset.attrib["format"], formats)
            self.assertEqual(xml_time(asset.attrib["start"]), 59)
            self.assertGreater(xml_time(asset.attrib["duration"]), 0)
            url = asset.find("media-rep").attrib["src"]
            self.assertIn(url, contents)
            self.assertFalse(url.startswith(("http:", "https:", "file:/")))
        parents = {child: parent for parent in root.iter() for child in parent}
        clips = list(sequence.iter("asset-clip"))
        self.assertEqual(len(clips), 2)
        generated = []
        for clip in clips:
            self.assertIn(clip.attrib["ref"], assets)
            self.assertEqual(xml_time(clip.attrib["duration"]), 1)
            self.assertIn("start", clip.attrib)
            self.assertIn("offset", clip.attrib)
            if int(clip.attrib.get("lane", "0")) > 0:
                generated.append(clip)
                self.assertNotEqual(parents[clip].tag, "spine")
                self.assertGreaterEqual(int(clip.attrib["lane"]), 2)
        self.assertEqual(len(generated), 1)
        camera = next(clip for clip in clips if clip not in generated)
        self.assertEqual(xml_time(camera.attrib["start"]), 60)
        self.assertEqual(xml_time(camera.attrib["offset"]), 3600)
        self.assertEqual(xml_time(generated[0].attrib["start"]), 59)
        anchor = parents[generated[0]]
        self.assertEqual(xml_time(generated[0].attrib["offset"]) - xml_time(anchor.attrib["start"]) + xml_time(anchor.attrib["offset"]), 3601)
        self.assertIn("CAMERA_A_LONG_REEL", contents["timeline.fcpxml"].decode())
        self.assertEqual(contents["timeline.fcpxml"], (GOLDENS / "timeline.fcpxml").read_bytes())

    def test_otio_and_fcpxml_timing_at_25_and_exact_drop_frame(self) -> None:
        for rate, drop_frame, nominal, hour in ((25, False, 25, 90000), ("30000/1001", True, 30, 107892)):
            with self.subTest(rate=rate):
                contents = archive_contents(snapshot(rate, drop_frame))
                timeline = otio.adapters.read_from_string(contents["timeline.otio"].decode(), "otio_json")
                again = otio.adapters.read_from_string(otio.adapters.write_to_string(timeline, "otio_json"), "otio_json")
                self.assertTrue(timeline.is_equivalent_to(again))
                camera = timeline.tracks[0].find_clips()[0]
                generated = timeline.tracks[-1].find_clips()[0]
                self.assertEqual(camera.source_range.start_time.value, 60 * nominal)
                self.assertEqual(camera.duration().value, nominal)
                self.assertEqual(generated.range_in_parent().start_time.value, nominal)
                self.assertAlmostEqual(camera.source_range.start_time.rate, float(Fraction(rate)))
                self.assertEqual(timeline.global_start_time.value, hour)
                root = ET.fromstring(contents["timeline.fcpxml"])
                sequence = root.find("./library/event/project/sequence")
                self.assertEqual(xml_time(sequence.attrib["tcStart"]), Fraction(hour) / Fraction(rate))
                self.assertEqual(xml_time(sequence.attrib["duration"]), Fraction(2 * nominal) / Fraction(rate))
                clips = list(sequence.iter("asset-clip"))
                primary = next(clip for clip in clips if int(clip.attrib.get("lane", "0")) == 0)
                connected = next(clip for clip in clips if int(clip.attrib.get("lane", "0")) > 0)
                self.assertEqual(xml_time(primary.attrib["start"]), Fraction(60 * nominal) / Fraction(rate))
                self.assertEqual(xml_time(connected.attrib["start"]), Fraction(59 * nominal) / Fraction(rate))
                parents = {child: parent for parent in sequence.iter() for child in parent}
                anchor = parents[connected]
                record = (xml_time(connected.attrib["offset"]) - xml_time(anchor.attrib["start"])
                          + xml_time(anchor.attrib["offset"]) - xml_time(sequence.attrib["tcStart"]))
                self.assertEqual(record, Fraction(nominal) / Fraction(rate))

    def test_generated_audio_has_its_own_track_in_every_format(self) -> None:
        document = snapshot()
        document["document"]["tracks"][0]["kind"] = "audio"
        document["document"]["tracks"][1]["kind"] = "audio"
        for asset in document["document"]["assets"]:
            asset["kind"] = "audio"
            asset["hasAudio"] = True
            asset["url"] = "silence.wav"
            asset["checksum"] = hashlib.sha256((MEDIA / "silence.wav").read_bytes()).hexdigest()
        contents = archive_contents(document)
        timeline = otio.adapters.read_from_string(contents["timeline.otio"].decode(), "otio_json")
        self.assertEqual(len(timeline.tracks), 3)
        self.assertTrue(all(track.kind == otio.schema.TrackKind.Audio for track in timeline.tracks))
        self.assertEqual(len(list(timeline.tracks[0].find_clips())), 1)
        self.assertEqual(len(list(timeline.tracks[1].find_clips())), 0)
        self.assertEqual(len(list(timeline.tracks[2].find_clips())), 1)
        root = ET.fromstring(contents["timeline.fcpxml"])
        clips = list(root.iter("asset-clip"))
        self.assertEqual(len(clips), 2)
        self.assertEqual(len({clip.attrib["lane"] for clip in clips}), 2)
        self.assertTrue(all(int(clip.attrib["lane"]) < 0 for clip in clips))
        for asset in root.findall("./resources/asset"):
            self.assertNotIn("audioChannels", asset.attrib)
            self.assertNotIn("audioRate", asset.attrib)
        edls = [data.decode() for name, data in contents.items() if name.endswith(".edl")]
        self.assertEqual(len(edls), 3)
        camera_edl = next(edl for edl in edls if "CAMERA_A_LONG_REEL" in edl)
        generated_edl = next(edl for edl in edls if "GEN_001" in edl)
        self.assertNotEqual(camera_edl, generated_edl)
        for edl in (camera_edl, generated_edl):
            self.assertEqual(next(line.split()[2] for line in edl.splitlines() if line[:3].isdigit()), "A")

    def test_edl_golden_timecodes_at_24_25_and_drop_frame(self) -> None:
        for rate, df, tag in ((24, False, "24"), (25, False, "25"), ("30000/1001", True, "2997df")):
            with self.subTest(rate=rate):
                contents = archive_contents(snapshot(rate, df))
                edls = {name: data for name, data in contents.items() if name.endswith(".edl")}
                self.assertEqual(len(edls), 3)
                for name, data in edls.items():
                    self.assertEqual(data, (GOLDENS / tag / Path(name).name).read_bytes())
                camera = next(data.decode() for data in edls.values() if "Camera" in data.decode() and "CAMERA_A_LONG_REEL" in data.decode())
                expected_in = "00:01:00;02" if df else "00:01:00:00"
                expected_out = "00:01:01;02" if df else "00:01:01:00"
                self.assertIn(expected_in, camera)
                self.assertIn(expected_out, camera)
                self.assertIn("DROP FRAME" if df else "NON-DROP FRAME", camera)
                events = [line.split() for line in camera.splitlines() if line[:3].isdigit()]
                self.assertEqual(len(events), 1)
                self.assertLessEqual(len(events[0][1]), 8)
                self.assertIn("GEN_001", next(data.decode() for data in edls.values() if "GEN_001" in data.decode()))

    def test_drop_frame_tenth_minute_and_invalid_skipped_labels(self) -> None:
        document = snapshot("30000/1001", True)
        document["document"]["assets"][0]["sourceTimecode"] = "00:09:59;00"
        contents = archive_contents(document)
        camera = next(data.decode() for name, data in contents.items() if name.endswith(".edl") and b"CAMERA_A_LONG_REEL" in data)
        self.assertIn("00:10:00;00", camera)
        for label in ("00:01:00;00", "00:01:00;01"):
            document["document"]["assets"][0]["sourceTimecode"] = label
            with self.subTest(label=label), self.assertRaises(ValueError):
                archive_contents(document)

    def test_manifest_media_checksums_provenance_and_no_absolute_paths(self) -> None:
        contents = archive_contents(snapshot())
        manifest = contents["manifest.json"].decode()
        self.assertIn("version-camera-1", manifest)
        self.assertIn("source_version_ids", manifest)
        self.assertIn("CAMERA_A_LONG_REEL", manifest)
        self.assertNotIn(str(MEDIA.resolve()), manifest)
        self.assertNotIn("https://", manifest)
        source_hashes = {hashlib.sha256((MEDIA / name).read_bytes()).hexdigest()
                         for name in ("camera.mp4", "generated.mp4")}
        archived_hashes = {hashlib.sha256(data).hexdigest() for name, data in contents.items() if name.startswith("media/")}
        self.assertEqual(archived_hashes, source_hashes)
        self.assertTrue(all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in contents))

    def test_rejects_missing_identity_corrupt_media_and_unsupported_edits(self) -> None:
        for field in ("versionId", "checksum", "sourceTimecode", "reelName", "provenance", "generated", "hasAudio"):
            document = snapshot()
            del document["document"]["assets"][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                archive_contents(document)
        document = snapshot()
        document["document"]["assets"][0]["checksum"] = "0" * 64
        with self.assertRaises(ValueError):
            archive_contents(document)
        document = snapshot()
        document["document"]["tracks"][0]["items"][0]["playbackRate"] = 2
        with self.assertRaises(ValueError):
            archive_contents(document)
        document = snapshot()
        document["document"]["tracks"][0]["items"][0]["sourceIn"] = 4
        with self.assertRaises(ValueError):
            archive_contents(document)
        document = snapshot()
        document["document"]["assets"][0]["url"] = "../outside.mp4"
        with self.assertRaises(ValueError):
            archive_contents(document)

    def test_gateway_contract_registration_and_export_is_free(self) -> None:
        spec = get_provider("remotion")
        self.assertEqual(generate_schemas(spec), load_committed_schemas(spec))
        schema = next(tool for tool in generate_schemas(spec) if tool["name"] == "export_nle_timeline")
        self.assertEqual(schema["inputSchema"]["required"], ["timeline_json"])
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "true"}):
            self.assertEqual(dispatch("remotion", "export_nle_timeline", {"timeline_json": "{}"})["status"], "dry_run")
            with self.assertRaises(ValueError):
                dispatch("remotion", "export_nle_timeline", {"timeline_json": {}})
        self.assertEqual(cost_for("remotion", "export_nle_timeline", {}).total_cents, 0)

    def test_gateway_dispatch_produces_a_real_local_archive_without_network(self) -> None:
        document = snapshot()
        for asset in document["document"]["assets"]:
            asset["url"] = str((MEDIA / asset["url"]).resolve())
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "AWS_LAMBDA_FUNCTION_NAME": "",
                                    "RENDERHAUS_MEDIA_DIR": str(MEDIA.resolve())}),
            patch("providers.remotion.api.ROOT", Path(directory)),
            patch("providers.remotion.api.DEPLOYMENT_PATH", Path(directory) / "missing.json"),
            patch("providers.nle.bundle.httpx.Client", side_effect=AssertionError("Unexpected network")),
            patch("providers.remotion.api.boto3.Session", side_effect=AssertionError("Unexpected AWS")),
        ):
            result = dispatch("remotion", "export_nle_timeline", {
                "timeline_json": json.dumps(document), "output_filename": "../../editor.zip",
            })
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["filename"], "editor.zip")
            self.assertTrue(Path(result["output_path"]).is_relative_to(Path(directory)))
            with zipfile.ZipFile(result["output_path"]) as archive:
                self.assertIsNone(archive.testzip())
                timeline = otio.adapters.read_from_string(archive.read("timeline.otio").decode(), "otio_json")
                self.assertEqual(len(timeline.find_clips()), 2)
                for clip in timeline.find_clips():
                    self.assertGreater(len(archive.read(clip.media_reference.target_url)), 0)

    def test_failed_checksum_leaves_no_partial_archive(self) -> None:
        document = snapshot()
        document["document"]["assets"][0]["checksum"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "handoff.zip"
            with self.assertRaises(ValueError):
                build_handoff(document, destination, media_roots=(MEDIA,), source_root=MEDIA)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_lambda_handoff_uploads_zip_and_returns_a_download_reference_offline(self) -> None:
        from lambdas.handler import handler

        document = snapshot()
        for asset in document["document"]["assets"]:
            asset["url"] = str((MEDIA / asset["url"]).resolve())
        captured = []
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"REMOTION_DRY_RUN": "false", "RENDERHAUS_PROVIDER": "remotion",
                                    "AWS_LAMBDA_FUNCTION_NAME": "offline-export-test",
                                    "REMOTION_APP_BUCKET_NAME": "offline-output",
                                    "RENDERHAUS_MEDIA_DIR": str(MEDIA.resolve())}),
            patch("providers.remotion.api.DEPLOYMENT_PATH", Path(directory) / "missing.json"),
            patch("providers.remotion.api.boto3.Session") as session,
            patch("providers.nle.bundle.httpx.Client", side_effect=AssertionError("Unexpected network")),
        ):
            s3 = session.return_value.client.return_value
            s3.upload_file.side_effect = lambda path, *_args, **_kwargs: captured.append(Path(path).read_bytes())
            s3.generate_presigned_url.return_value = "https://example.test/offline-download.zip"
            result = handler({"_tool_name": "export_nle_timeline", "timeline_json": json.dumps(document)}, None)
            self.assertEqual(result["status"], "succeeded")
            self.assertNotIn("output_path", result)
            self.assertEqual(result["url"], "https://example.test/offline-download.zip")
            self.assertEqual(result["bucket_name"], "offline-output")
            self.assertEqual(s3.upload_file.call_args.kwargs["ExtraArgs"]["ContentType"], "application/zip")
            with zipfile.ZipFile(io.BytesIO(captured[0])) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("timeline.otio", archive.namelist())
                self.assertEqual(len([name for name in archive.namelist() if name.startswith("media/")]), 2)

    def test_version_conflicts_and_generated_track_id_collisions(self) -> None:
        document = snapshot()
        document["document"]["assets"][1]["versionId"] = "version-camera-1"
        with self.assertRaises(ValueError):
            archive_contents(document)
        document = snapshot()
        document["document"]["tracks"][1]["id"] = "renderhaus-generated-d804c07f273fb64d"
        with self.assertRaises(ValueError):
            archive_contents(document)

    def test_provenance_strips_signed_urls_and_credentials(self) -> None:
        document = snapshot()
        document["document"]["assets"][0]["provenance"].update({
            "description": "Input HTTPS://name:password@example.test/media?X-Amz-Signature=SECRET#private",
            "apiKey": "DO_NOT_PACKAGE", "nested": {"authorization": "DO_NOT_PACKAGE"},
        })
        contents = archive_contents(document)
        for name in ("timeline.otio", "timeline.fcpxml", "manifest.json"):
            with self.subTest(file=name):
                text = contents[name].decode()
                self.assertNotIn("SECRET", text)
                self.assertNotIn("DO_NOT_PACKAGE", text)
                self.assertNotIn("name:password", text)
                self.assertNotIn("#private", text)

    def test_clip_duration_matches_remotion_end_minus_start_rounding(self) -> None:
        document = snapshot()
        clip = document["document"]["tracks"][0]["items"][0]
        clip.update(start=0.02, duration=0.06)
        contents = archive_contents(document)
        timeline = otio.adapters.read_from_string(contents["timeline.otio"].decode(), "otio_json")
        self.assertEqual(timeline.tracks[0].find_clips()[0].duration().value, 2)
        root = ET.fromstring(contents["timeline.fcpxml"])
        primary = root.find("./library/event/project/sequence/spine/asset-clip")
        self.assertEqual(xml_time(primary.attrib["duration"]), Fraction(1, 12))
        edl = next(data.decode() for name, data in contents.items() if name.endswith(".edl") and b"CAMERA_A_LONG_REEL" in data)
        self.assertIn("01:00:00:00 01:00:00:02", edl)

    def test_fcpxml_zero_volume_is_an_exact_mute(self) -> None:
        for kind, name in (("audio", "silence.wav"), ("video", "camera-av.mp4")):
            with self.subTest(kind=kind):
                document = snapshot()
                document["document"]["tracks"][0]["items"][0]["volume"] = 0
                if kind == "audio":
                    for track in document["document"]["tracks"]:
                        track["kind"] = "audio"
                for asset in document["document"]["assets"]:
                    asset.update(kind=kind, hasAudio=True, url=name,
                                 checksum=hashlib.sha256((MEDIA / name).read_bytes()).hexdigest())
                root = ET.fromstring(archive_contents(document)["timeline.fcpxml"])
                clip = next(element for element in root.iter("asset-clip") if element.attrib["name"] == "Camera")
                if kind == "audio":
                    self.assertEqual(clip.attrib["enabled"], "0")
                else:
                    self.assertEqual(clip.attrib["srcEnable"], "video")
                self.assertIsNone(clip.find("adjust-volume"))


if __name__ == "__main__":
    unittest.main()
