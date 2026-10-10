#!/usr/bin/env python3
"""Build our synthetic films and fit provisional thresholds from labelled local MP4s."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.remotion.motion_carry import CHECKS, FPS, decode, measure_frames, metrics  # noqa: E402
from providers.ffmpeg.sandbox import sha256_file  # noqa: E402


def build_fixtures(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    names = ["carrying", "slideshow", "fade_replace", *CHECKS, "blurred_fast_move", "intentional_exit"]
    films = []
    for name in names:
        beats = [0, .9, 2.3, 3.4, 6]
        if name == "uniform_cadence":
            beats = [0, 1.5, 3, 4.5, 6]
        timeline = {"beats_s": beats, "elements": [{"id": "product-card", "start_s": 0, "end_s": 6,
                                                     "main_subject": True,
                                                     "intentional_exit": name == "intentional_exit"}]}
        frames = []
        for index in range(144):
            t = index/24
            moving_t = t
            if name != "no_rests":
                moving_t -= min(max(t-.25, 0), .4) + min(max(t-4.5, 0), .9)
            x = 18 + 12*moving_t
            if name in {"unblurred_fast_move", "blurred_fast_move"} and 2.6 <= t <= 3.1:
                x += 40*np.sin((t-2.6)*2*np.pi)
            if name in {"subject_exit", "intentional_exit"} and t >= 4:
                x += 100*(t-4)
            beat = min(3, sum(t >= boundary for boundary in beats[1:-1]))
            if name in {"slideshow", "fade_replace"}:
                x = [20, 90, 35, 100][beat]
            layer = Image.new("RGB", (160, 90))
            draw = ImageDraw.Draw(layer)
            draw.rectangle((round(x), 27, round(x)+28, 55), fill=(40, 170, 235))
            draw.rectangle((round(x)+5, 32, round(x)+23, 36), fill=(220, 240, 255))
            if name == "blurred_fast_move" and 2.6 <= t <= 3.1:
                layer = layer.filter(ImageFilter.GaussianBlur(3))
            if name == "fade_replace":
                distance = min(abs(t-b) for b in beats[1:-1])
                opacity = min(1, distance/.25)
                layer = Image.fromarray((np.asarray(layer)*opacity).astype(np.uint8))
            # These labels are our content, unrelated to any external look or template.
            ImageDraw.Draw(layer).text((8, 75), ["LAUNCH", "PRODUCT", "DETAIL", "TRY IT"][beat], fill=(90, 90, 90))
            frames.append(np.asarray(layer))
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            raw = work / "video.rgb"
            raw.write_bytes(np.stack(frames).tobytes())
            rate = 48000
            times = np.arange(6*rate)/rate
            samples = .18*np.sin(2*np.pi*330*times)
            for boundary in beats[1:-1]:
                samples += .12*np.exp(-((times-boundary)/.02)**2)
            if name == "clipped_audio":
                samples = np.clip(1.8*np.sin(2*np.pi*330*times), -1, 1)
            audio = work / "audio.wav"
            with wave.open(str(audio), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(rate)
                target.writeframes((np.clip(samples, -1, 1)*32767).astype("<i2").tobytes())
            destination = directory / f"{name}.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo",
                            "-pixel_format", "rgb24", "-video_size", "160x90", "-framerate", "24",
                            "-i", str(raw), "-i", str(audio), "-c:v", "mpeg4", "-q:v", "2",
                            "-threads", "1", "-c:a", "alac", "-t", "6", "-movflags", "+faststart",
                            str(destination)], check=True, capture_output=True, timeout=30)
        if name == "carrying":
            labels = {"carry": True, **{check: True for check in CHECKS}}
        elif name in {"slideshow", "fade_replace"}:
            labels = {"carry": False}
        elif name in CHECKS:
            labels = {name: False}
        else:
            labels = {"unblurred_fast_move" if name == "blurred_fast_move" else "subject_exit": True}
        films.append({"name": name, "file": destination.name, "sha256": sha256_file(destination),
                      "timeline": timeline, "labels": labels})
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"origin": "Independent Renderhaus synthetic product-card films; Pillow and installed ffmpeg, not Remotion browser output.",
                                    "films": films}, indent=2) + "\n")
    return manifest


def calibrate(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    measurements = []
    for film in manifest["films"]:
        path = manifest_path.parent / film["file"]
        if film.get("sha256") and sha256_file(path) != film["sha256"]:
            raise ValueError(f"Calibration film changed: {film['name']}")
        frames, audio = decode(path)
        measurements.append((film, measure_frames(frames, FPS, timeline=film.get("timeline"), audio=audio)))
    positives = [m for f, m in measurements if f["labels"].get("no_rests") is True]
    negatives = [m for f, m in measurements if f["labels"].get("no_rests") is False]
    if not positives or not negatives:
        raise ValueError("Label held-moment positives and no-rest negatives to calibrate stillness.")
    held_noise = max(float(np.quantile(m["frame_deltas"], .1)) for m in positives)
    moving_floor = min(float(np.quantile(m["frame_deltas"], .1)) for m in negatives)
    if moving_floor <= held_noise:
        raise ValueError("Held-frame noise and continuous-motion samples do not separate.")
    still_delta = (held_noise+moving_floor)/2
    scores = [{"name": f["name"], "sha256": sha256_file(manifest_path.parent/f["file"]),
               "labels": f["labels"], "metrics": metrics(m, still_delta)} for f, m in measurements]
    thresholds, separation = {"still_delta": still_delta}, {}
    for metric in ["carry", *CHECKS]:
        pos = [s["metrics"][metric] for s in scores if s["labels"].get(metric) is True]
        neg = [s["metrics"][metric] for s in scores if s["labels"].get(metric) is False]
        if not pos or not neg:
            raise ValueError(f"Both positive and negative labels are required for {metric}.")
        high_pass = metric in {"carry", "uniform_cadence", "no_rests"}
        positive_edge, negative_edge = (min(pos), max(neg)) if high_pass else (max(pos), min(neg))
        separated = positive_edge > negative_edge if high_pass else positive_edge < negative_edge
        if not separated:
            raise ValueError(f"Classes do not separate for {metric}: {pos}, {neg}")
        thresholds[metric] = (positive_edge+negative_edge)/2
        separation[metric] = {"positive_edge": positive_edge, "negative_edge": negative_edge,
                              "separated": separated, "positive_count": len(pos), "negative_count": len(neg)}
    return {"schema_version": 1, "provisional": True, "method": "midpoint of labelled class extrema",
            "origin": manifest.get("origin", "Operator-labelled Renderhaus deliverables"),
            "manifest_sha256": sha256_file(manifest_path), "thresholds": thresholds,
            "stillness_fit": {"held_noise_p10": held_noise, "moving_floor_p10": moving_floor},
            "separation": separation, "scores": scores}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-fixtures", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_fixtures(args.build_fixtures) if args.build_fixtures else args.manifest
    if manifest is None:
        parser.error("Supply --manifest or --build-fixtures.")
    config = calibrate(manifest)
    args.output.write_text(json.dumps(config, allow_nan=False, indent=2) + "\n")
    print(f"Calibrated {len(config['scores'])} films. All thresholds PROVISIONAL. Saved {args.output}.")


if __name__ == "__main__":
    main()
