from __future__ import annotations

from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from providers.remotion import api, local, mp4_probe


ERROR = "Local source/output is not a supported media container."


def box(kind: bytes, payload: bytes = b"", *, extended: bool = False, zero: bool = False) -> bytes:
    if zero:
        return struct.pack(">I4s", 0, kind) + payload
    if extended:
        return struct.pack(">I4sQ", 1, kind, len(payload) + 16) + payload
    return struct.pack(">I4s", len(payload) + 8, kind) + payload


def header(kind: bytes, timescale: int, duration: int, version: int = 0) -> bytes:
    fields = (
        struct.pack(">QQIQ", 0, 0, timescale, duration)
        if version == 1
        else struct.pack(">IIII", 0, 0, timescale, duration)
    )
    suffix = b"\0" * (80 if kind == b"mvhd" else 4)
    return box(kind, bytes([version, 0, 0, 0]) + fields + suffix)


def track_header(*, version: int = 0, rotation: int = 0, flags: int = 7,
                 matrix: tuple[int, ...] | None = None) -> bytes:
    matrices = {
        0: (65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824),
        90: (0, 65536, 0, -65536, 0, 0, 720 * 65536, 0, 1073741824),
        180: (-65536, 0, 0, 0, -65536, 0, 1280 * 65536, 720 * 65536, 1073741824),
        270: (0, -65536, 0, 65536, 0, 0, 0, 1280 * 65536, 1073741824),
    }
    timing = struct.pack(">QQIIQ" if version == 1 else ">IIIII", 0, 0, 1, 0, 60000)
    return box(b"tkhd", bytes([version]) + flags.to_bytes(3, "big") + timing + b"\0" * 16
               + struct.pack(">9i", *(matrix if matrix is not None else matrices[rotation]))
               + struct.pack(">II", 1280 * 65536, 720 * 65536))


def track(
    *,
    kind: bytes = b"vide",
    codec: bytes = b"avc1",
    timescale: int = 30000,
    duration: int = 60000,
    version: int = 0,
    samples: int = 60,
    sizes: list[int] | None = None,
    runs: list[tuple[int, int]] | None = None,
    sample_size: int = 100,
    stsz: bytes | None = None,
    stts: bytes | None = None,
    stsd: bytes | None = None,
    dimensions: tuple[int, int] | None = None,
    tkhd: bytes | None = None,
) -> bytes:
    if stsz is None:
        if sizes is not None:
            sample_size, samples = 0, len(sizes)
        entries = b"" if sizes is None else b"".join(struct.pack(">I", n) for n in sizes)
        stsz = box(b"stsz", b"\0" * 4 + struct.pack(">II", sample_size, samples) + entries)
    if stts is None:
        runs = [(samples, 1000)] if runs is None else runs
        stts = box(
            b"stts",
            b"\0" * 4
            + struct.pack(">I", len(runs))
            + b"".join(struct.pack(">II", *run) for run in runs),
        )
    if stsd is None:
        payload = b"\0" * 6 + struct.pack(">H", 1) + b"\0" * (70 if kind == b"vide" else 20)
        if kind == b"vide" and dimensions is not None:
            payload = payload[:24] + struct.pack(">HH", *dimensions) + payload[28:]
        sample_entry = box(codec, payload)
        stsd = box(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + sample_entry)
    handler = box(b"hdlr", b"\0" * 8 + kind + b"\0" * 12)
    return box(
        b"trak",
        (tkhd or b"") + box(
            b"mdia",
            header(b"mdhd", timescale, duration, version)
            + handler
            + box(b"minf", box(b"stbl", stsd + stts + stsz)),
        ),
    )


def movie(
    *tracks: bytes,
    duration: int = 60000,
    timescale: int = 30000,
    version: int = 0,
    mvhd: bool = True,
    extended: bool = False,
    zero_mdat: bool = False,
    extra: bytes = b"",
    ftyp: bool = True,
) -> bytes:
    prefix = box(b"ftyp", b"isom\0\0\0\0isommp42") if ftyp else b""
    metadata = header(b"mvhd", timescale, duration, version) if mvhd else b""
    return (
        prefix
        + box(b"moov", metadata + b"".join(tracks) + extra, extended=extended)
        + box(b"mdat", b"\0" * 10000, zero=zero_mdat)
    )


class MP4ProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "clip.mp4"

    def probe(self, content: bytes, *, limit: int = local.MAX_MEDIA_BYTES) -> dict:
        self.path.write_bytes(content)
        return mp4_probe.probe(self.path, max_bytes=limit)

    def unsupported(self, content: bytes, **kwargs: int) -> None:
        with self.assertRaises(ValueError) as caught:
            self.probe(content, **kwargs)
        self.assertEqual(str(caught.exception), ERROR)

    def test_video_constant_sample_sizes(self) -> None:
        content = movie(track())
        result = self.probe(content)
        self.assertEqual(
            result["streams"],
            [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "avg_frame_rate": "30/1",
                    "bit_rate": 24000,
                }
            ],
        )
        self.assertEqual(result["format"]["duration"], 2.0)
        self.assertEqual(result["format"]["bit_rate"], len(content) * 4)

    def test_video_and_audio_variable_sample_sizes(self) -> None:
        result = self.probe(
            movie(
                track(sizes=[100, 200, 300], runs=[(3, 20000)]),
                track(kind=b"soun", codec=b"mp4a", samples=2, sizes=[400, 600], runs=[(2, 30000)]),
            )
        )
        self.assertEqual([s["codec_type"] for s in result["streams"]], ["video", "audio"])
        self.assertEqual(result["streams"][0]["avg_frame_rate"], "3/2")
        self.assertEqual(result["streams"][0]["bit_rate"], 2400)
        self.assertEqual(
            result["streams"][1],
            {"codec_type": "audio", "codec_name": "aac", "avg_frame_rate": "0/0", "bit_rate": 4000},
        )

    def test_visual_sample_entry_reports_dimensions(self) -> None:
        for codec, size in ((b"avc1", (1280, 720)), (b"hvc1", (1920, 1080)),
                            (b"av01", (720, 1280))):
            with self.subTest(codec=codec, size=size):
                result = self.probe(movie(track(codec=codec, dimensions=size)))
                self.assertEqual((result["streams"][0]["width"], result["streams"][0]["height"]), size)

    def test_stdlib_fallback_reports_dimensions(self) -> None:
        self.path.write_bytes(movie(track(dimensions=(1280, 720))))
        with patch.object(local.shutil, "which", return_value=None):
            video = local._probe(self.path)["streams"][0]
        self.assertEqual((video["width"], video["height"]), (1280, 720))

    def test_zero_sample_entry_dimensions_remain_unknown(self) -> None:
        for size in ((0, 720), (1280, 0), (0, 0)):
            with self.subTest(size=size):
                video = self.probe(movie(track(dimensions=size)))["streams"][0]
                self.assertNotIn("width", video)
                self.assertNotIn("height", video)

    def test_track_header_quarter_turns_report_display_dimensions(self) -> None:
        for version in (0, 1):
            for rotation in (90, 270):
                for flags in (1, 3, 7, 15):
                    with self.subTest(version=version, rotation=rotation, flags=flags):
                        video = self.probe(movie(track(dimensions=(1280, 720),
                            tkhd=track_header(version=version, rotation=rotation, flags=flags))))["streams"][0]
                        self.assertEqual((video["width"], video["height"]), (720, 1280))

    def test_track_header_identity_and_half_turn_preserve_dimensions(self) -> None:
        for version in (0, 1):
            for rotation in (0, 180):
                with self.subTest(version=version, rotation=rotation):
                    video = self.probe(movie(track(dimensions=(1280, 720),
                        tkhd=track_header(version=version, rotation=rotation))))["streams"][0]
                    self.assertEqual(video, {"codec_type": "video", "codec_name": "h264",
                        "width": 1280, "height": 720, "avg_frame_rate": "30/1", "bit_rate": 24000})

    def test_track_header_unknown_matrix_omits_dimensions(self) -> None:
        for version in (0, 1):
            for matrix in (
                (46341, 46341, 0, -46341, 46341, 0, 0, 0, 1073741824),
                (131072, 0, 0, 0, 131072, 0, 0, 0, 1073741824),
                (-65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824),
                (65536, 0, 1, 0, 65536, 0, 0, 0, 1073741824),
                (65536, 0, 0, 0, 65536, 0, 0, 0, 65536),
                (0,) * 9,
            ):
                with self.subTest(version=version, matrix=matrix):
                    video = self.probe(movie(track(dimensions=(1280, 720),
                        tkhd=track_header(version=version, matrix=matrix))))["streams"][0]
                    self.assertNotIn("width", video)
                    self.assertNotIn("height", video)
                    self.assertEqual(video["avg_frame_rate"], "30/1")

    def test_track_header_invalid_version_and_bounds_are_rejected(self) -> None:
        headers = [track_header(version=2)]
        for version in (0, 1):
            valid = track_header(version=version)
            for length in (3, len(valid) - 9, len(valid) - 16, len(valid) - 45):
                headers.append(box(b"tkhd", valid[8:8 + length]))
        for index, tkhd in enumerate(headers):
            with self.subTest(index=index, size=len(tkhd)):
                self.unsupported(movie(track(dimensions=(1280, 720), tkhd=tkhd)))

    def test_track_header_parent_and_uniqueness_are_enforced(self) -> None:
        for content in (movie(track(dimensions=(1280, 720)), extra=track_header()),
                        movie(track(dimensions=(1280, 720), tkhd=track_header() + track_header()))):
            with self.subTest(size=len(content)):
                self.unsupported(content)

    def test_extended_box_size(self) -> None:
        self.assertEqual(
            self.probe(movie(track(), extended=True))["streams"][0]["avg_frame_rate"], "30/1"
        )

    def test_mdhd_and_mvhd_version_one(self) -> None:
        result = self.probe(
            movie(
                track(version=1, timescale=30000, duration=60060, runs=[(60, 1001)]),
                duration=60060,
                version=1,
            )
        )
        self.assertEqual(result["streams"][0]["avg_frame_rate"], "30000/1001")
        self.assertAlmostEqual(result["format"]["duration"], 2.002)

    def test_version_one_duration_larger_than_uint32(self) -> None:
        duration = (1 << 32) + 1
        result = self.probe(
            movie(
                track(
                    version=1,
                    timescale=1,
                    duration=duration,
                    samples=2,
                    runs=[(1, 0xFFFFFFFF), (1, 2)],
                ),
                duration=duration,
                timescale=1,
                version=1,
            )
        )
        self.assertEqual(result["format"]["duration"], float(duration))

    def test_vfr_uses_sample_timing(self) -> None:
        result = self.probe(
            movie(track(samples=30, duration=45000, runs=[(15, 1000), (15, 2000)]), duration=45000)
        )
        self.assertEqual(result["streams"][0]["avg_frame_rate"], "20/1")
        self.assertEqual(result["streams"][0]["bit_rate"], 16000)

    def test_missing_sample_timing_uses_media_duration(self) -> None:
        self.assertEqual(self.probe(movie(track(stts=b"")))["streams"][0]["avg_frame_rate"], "30/1")

    def test_moov_after_media_payload(self) -> None:
        content = movie(track())
        prefix_size = struct.unpack(">I", content[:4])[0]
        moov_size = struct.unpack(">I", content[prefix_size : prefix_size + 4])[0]
        result = self.probe(
            content[:prefix_size]
            + content[prefix_size + moov_size :]
            + content[prefix_size : prefix_size + moov_size]
        )
        self.assertEqual(result["streams"][0]["avg_frame_rate"], "30/1")

    def test_missing_movie_header_uses_longest_track(self) -> None:
        result = self.probe(
            movie(track(), track(kind=b"soun", duration=90000, samples=90), mvhd=False)
        )
        self.assertEqual(result["format"]["duration"], 3.0)

    def test_unspecified_movie_duration_uses_longest_track(self) -> None:
        for duration in (0, 0xFFFFFFFF):
            with self.subTest(duration=duration):
                result = self.probe(movie(track(), duration=duration))
                self.assertEqual(result["format"]["duration"], 2.0)

    def test_sample_payload_cannot_exceed_file_size(self) -> None:
        self.unsupported(movie(track(sample_size=0xFFFFFFFF)))

    def test_quicktime_without_ftyp(self) -> None:
        self.assertEqual(
            self.probe(movie(track(codec=b"hvc1"), ftyp=False))["streams"][0]["codec_name"], "hevc"
        )

    def test_zero_size_box_extends_to_parent_end(self) -> None:
        self.assertEqual(
            self.probe(movie(track(), zero_mdat=True))["streams"][0]["avg_frame_rate"], "30/1"
        )

    def test_non_audio_video_track_is_skipped(self) -> None:
        result = self.probe(movie(track(), track(kind=b"text", codec=b"text")))
        self.assertEqual(len(result["streams"]), 1)

    def test_truncation_and_invalid_box_bounds(self) -> None:
        valid = movie(track())
        for content in (
            b"",
            valid[:-1],
            valid[:10],
            b"\0\0\0\x07moov",
            struct.pack(">I4sQ", 1, b"moov", 15),
            box(b"free") + b"x",
        ):
            with self.subTest(content=content[:16]):
                self.unsupported(content)

    def test_huge_stsz_counts_are_rejected(self) -> None:
        for sample_size in (0, 1):
            hostile = box(b"stsz", b"\0" * 4 + struct.pack(">II", sample_size, 0xFFFFFFFF))
            with self.subTest(sample_size=sample_size):
                self.unsupported(movie(track(stsz=hostile)))

    def test_huge_stts_count_is_rejected(self) -> None:
        hostile = box(b"stts", b"\0" * 4 + struct.pack(">I", 0xFFFFFFFF))
        self.unsupported(movie(track(stts=hostile)))

    def test_sample_timing_count_must_match_sample_sizes(self) -> None:
        self.unsupported(movie(track(samples=60, runs=[(59, 1000)])))

    def test_deep_container_nesting_is_rejected(self) -> None:
        nested = b""
        for _ in range(20):
            nested = box(b"udta", nested)
        self.unsupported(movie(track(), extra=nested))

    def test_excessive_box_count_is_rejected(self) -> None:
        self.unsupported(movie(track()) + box(b"free") * 10001)

    def test_excessive_track_count_is_rejected(self) -> None:
        self.unsupported(movie(*[track() for _ in range(65)]))

    def test_file_size_limit_is_enforced(self) -> None:
        self.unsupported(movie(track()), limit=32)

    def test_invalid_time_headers_are_rejected(self) -> None:
        for content in (
            movie(track(timescale=0)),
            movie(track(version=2)),
            movie(track(duration=0)),
            movie(track(), timescale=0),
        ):
            with self.subTest(content=content[:16]):
                self.unsupported(content)

    def test_invalid_stsd_entry_is_rejected(self) -> None:
        for entries in (struct.pack(">I", 0xFFFFFFFF), struct.pack(">I", 1) + b"\0\0\0\x04avc1"):
            self.unsupported(movie(track(stsd=box(b"stsd", b"\0" * 4 + entries))))

    def test_fragmented_mp4_with_empty_sample_tables_is_rejected(self) -> None:
        self.unsupported(movie(track(samples=0, duration=0, runs=[])) + box(b"moof", box(b"traf")))

    def test_webm_header_is_unsupported(self) -> None:
        self.unsupported(b"\x1a\x45\xdf\xa3" + b"\0" * 32)

    def test_probe_fallback_returns_measured_metadata(self) -> None:
        self.path.write_bytes(movie(track()))
        with patch.object(local.shutil, "which", return_value=None):
            result = local._probe(self.path)
        self.assertEqual(result["streams"][0]["avg_frame_rate"], "30/1")
        self.assertEqual(result["streams"][0]["bit_rate"], 24000)

    def test_ffprobe_preferred_without_changing_subprocess_arguments(self) -> None:
        expected = {
            "streams": [{"codec_type": "video", "avg_frame_rate": "24/1", "width": 1280, "height": 720}],
            "format": {"duration": "2.0"},
        }
        with (
            patch.object(local.shutil, "which", return_value="/usr/bin/ffprobe"),
            patch.object(
                local.subprocess,
                "run",
                return_value=Mock(returncode=0, stdout=json.dumps(expected).encode()),
            ) as run,
            patch.object(local.mp4_probe, "probe", side_effect=AssertionError("fallback used")),
        ):
            self.assertEqual(local._probe(self.path), expected)
        run.assert_called_once_with(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                local.FORMATS,
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(self.path),
            ],
            capture_output=True,
            timeout=30,
        )

    def test_fallback_reuses_media_size_limit(self) -> None:
        self.path.write_bytes(movie(track()))
        with (
            patch.object(local.shutil, "which", return_value=None),
            patch.object(local, "MAX_MEDIA_BYTES", 32),
            self.assertRaises(ValueError) as caught,
        ):
            local._probe(self.path)
        self.assertEqual(str(caught.exception), ERROR)

    def test_non_iso_local_source_with_measured_fps_can_build_timeline(self) -> None:
        self.path = self.path.with_suffix(".webm")
        self.path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 32)
        with (
            patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": self.folder.name}),
            patch.object(local.shutil, "which", return_value=None),
        ):
            result = api.build_timeline_props(
                "Measured WebM",
                [
                    {
                        "kind": "video",
                        "output_path": str(self.path),
                        "duration_seconds": 2,
                        "source_fps": 24,
                    }
                ],
            )
        self.assertEqual(result["renderConfig"]["fps"], 24)

    def test_non_iso_source_without_measurement_keeps_primary_video_message(self) -> None:
        self.path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\0" * 32)
        with (
            patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": self.folder.name}),
            patch.object(local.shutil, "which", return_value=None),
            self.assertRaisesRegex(
                ValueError, "Download the primary video for ffprobe or supply measured source_fps"
            ),
        ):
            api.build_timeline_props(
                "Unmeasured WebM",
                [{"kind": "video", "output_path": str(self.path), "duration_seconds": 2}],
            )

    def test_remote_non_iso_source_keeps_measurements_or_requests_fps(self) -> None:
        body = b"\x1a\x45\xdf\xa3" + b"\0" * 32
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        client = httpx.Client
        for metadata in ({"source_fps": 24}, {"source_fps": 24, "source_bitrate": 1000}, {}):
            with (
                self.subTest(metadata=metadata),
                patch.dict(os.environ, {"REMOTION_LOCAL_MEDIA_HOSTS": ""}),
                patch.object(local.shutil, "which", return_value=None),
                patch.object(
                    local.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]
                ),
                patch.object(
                    local.httpx,
                    "Client",
                    side_effect=lambda **kwargs: client(transport=transport, **kwargs),
                ),
            ):
                visual = {
                    "kind": "video",
                    "url": "https://v3.fal.media/clip.webm",
                    "duration_seconds": 2,
                    **metadata,
                }
                if not metadata:
                    with self.assertRaisesRegex(
                        ValueError,
                        "Download the primary video for ffprobe or supply measured source_fps",
                    ):
                        api.build_timeline_props("WebM", [visual], measure_remote=True)
                    continue
                result = api.build_timeline_props("WebM", [visual], measure_remote=True)
                self.assertEqual(result["renderConfig"]["fps"], 24)
                if "source_bitrate" in metadata:
                    self.assertEqual(result["renderConfig"]["videoBitrate"], 1250)

    def test_measured_fps_does_not_hide_malformed_mp4(self) -> None:
        self.path.write_bytes(movie(track())[:-1])
        with (
            patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": self.folder.name}),
            patch.object(local.shutil, "which", return_value=None),
            self.assertRaises(ValueError),
        ):
            api.build_timeline_props(
                "Broken MP4",
                [
                    {
                        "kind": "video",
                        "output_path": str(self.path),
                        "duration_seconds": 2,
                        "source_fps": 24,
                    }
                ],
            )


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required for generated media")
class GeneratedMP4ProbeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffprobe"), "ffprobe required to verify the written display matrix")
    def test_generated_quarter_turn_video_reports_display_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.mp4"
            rotated = Path(temporary) / "rotated.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=24:duration=0.25", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source),
            ], check=True, timeout=30)
            help_text = subprocess.check_output(["ffmpeg", "-hide_banner", "-h", "full"],
                                                stderr=subprocess.STDOUT, timeout=30)
            rotation = ["-display_rotation", "90"] if b"-display_rotation" in help_text else []
            subprocess.run([
                "ffmpeg", "-v", "error", *rotation, "-i", str(source), "-c", "copy",
                *([] if rotation else ["-metadata:s:v:0", "rotate=90"]), str(rotated),
            ], check=True, timeout=30)
            encoded = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(rotated),
            ], timeout=30))["streams"][0]
            if not any(abs(side.get("rotation", 0)) == 90 for side in encoded.get("side_data_list", [])):
                self.skipTest("Installed ffmpeg did not write a quarter-turn display matrix.")
            self.assertEqual((encoded["width"], encoded["height"]), (1280, 720))
            video = mp4_probe.probe(rotated, max_bytes=local.MAX_MEDIA_BYTES)["streams"][0]
            self.assertEqual((video["width"], video["height"]), (720, 1280))
            self.assertEqual(video["avg_frame_rate"], "24/1")

    def test_generated_video_and_audio_match_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for audio, extension, fps in ((False, ".mp4", "30000/1001"), (True, ".mov", "24")):
                with self.subTest(audio=audio, extension=extension):
                    path = Path(temporary) / f"clip{extension}"
                    command = [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"testsrc2=size=64x64:rate={fps}:duration=1",
                    ]
                    if audio:
                        command += [
                            "-f",
                            "lavfi",
                            "-i",
                            "sine=frequency=440:duration=1",
                            "-c:a",
                            "aac",
                        ]
                    subprocess.run(
                        [*command, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                        check=True,
                        timeout=30,
                    )
                    result = mp4_probe.probe(path, max_bytes=local.MAX_MEDIA_BYTES)
                    self.assertEqual(
                        [s["codec_type"] for s in result["streams"]],
                        ["video", "audio"] if audio else ["video"],
                    )
                    self.assertEqual(
                        Fraction(result["streams"][0]["avg_frame_rate"]), Fraction(fps)
                    )
                    self.assertEqual((result["streams"][0]["width"], result["streams"][0]["height"]), (64, 64))
                    if not shutil.which("ffprobe"):
                        continue
                    expected = json.loads(
                        subprocess.check_output(
                            [
                                "ffprobe",
                                "-v",
                                "error",
                                "-show_streams",
                                "-show_format",
                                "-of",
                                "json",
                                str(path),
                            ],
                            timeout=30,
                        )
                    )
                    self.assertAlmostEqual(
                        result["format"]["duration"],
                        float(expected["format"]["duration"]),
                        delta=0.001,
                    )
                    self.assertAlmostEqual(
                        result["format"]["bit_rate"], int(expected["format"]["bit_rate"]), delta=1
                    )
                    for actual, measured in zip(
                        result["streams"], expected["streams"], strict=True
                    ):
                        if actual["codec_type"] == "video":
                            self.assertEqual((actual["width"], actual["height"]), (64, 64))
                            self.assertEqual((actual["width"], actual["height"]),
                                             (measured["width"], measured["height"]))
                            self.assertEqual(
                                Fraction(actual["avg_frame_rate"]),
                                Fraction(measured["avg_frame_rate"]),
                            )
                        else:
                            self.assertEqual(actual["avg_frame_rate"], "0/0")
                        self.assertAlmostEqual(
                            actual["bit_rate"], int(measured["bit_rate"]), delta=1
                        )


if __name__ == "__main__":
    unittest.main()
