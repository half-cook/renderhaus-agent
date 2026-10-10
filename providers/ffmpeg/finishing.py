from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path
import re
import shutil
import time

from providers.ffmpeg import delivery
from providers.ffmpeg.commands import Command, THREADS, _ffmpeg_input, _input
from providers.ffmpeg.sandbox import MAX_OUTPUT_BYTES, input_file, output_file, sha256_file


FONTS = {
    "dejavu_sans": ("DejaVu Sans", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
    "dejavu_serif": ("DejaVu Serif", Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")),
    "dejavu_mono": ("DejaVu Sans Mono", Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")),
}
GRADE_PRESETS = {
    "none": (1, 1, 0, 0),
    "warm": (1, 1, .10, -.10),
    "cool": (1, 1, -.10, .10),
    "contrast": (1.12, 1.05, 0, 0),
}
CLEANUP_PRESETS = {"dialogue": -50, "gentle": -60, "music": -55}
EQ_PRESETS = {
    "neutral": "equalizer=f=1500:t=q:w=1:g=0",
    "dialogue": "equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3000:t=q:w=1:g=2",
    "warm": "equalizer=f=180:t=q:w=1:g=1.5,equalizer=f=5000:t=q:w=1:g=-1.5",
}
_STYLE_FORMAT = ("name", "fontname", "fontsize", "primarycolour", "secondarycolour",
                 "outlinecolour", "backcolour", "bold", "italic", "underline", "strikeout",
                 "scalex", "scaley", "spacing", "angle", "borderstyle", "outline", "shadow",
                 "alignment", "marginl", "marginr", "marginv", "encoding")
_EVENT_FORMAT = ("layer", "start", "end", "style", "name", "marginl", "marginr", "marginv",
                 "effect", "text")
_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_SUBTITLE_BYTES = 1024 * 1024
_CUBE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def cues_from_arguments(items: list[dict]) -> list[Cue]:
    if not 1 <= len(items) <= 1000:
        raise ValueError("Timed text requires 1 to 1000 cues.")
    cues = []
    previous_end = 0
    for item in items:
        start, end, text = item["start"], item["end"], item["text"]
        if (not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= 600
                or end - start < .001 - 1e-12 or start < previous_end
                or round(end * 1000) <= round(start * 1000)):
            raise ValueError("Cue times must be finite, sorted, non-overlapping, within 600 seconds and at least 1 ms apart.")
        if (not isinstance(text, str) or not 1 <= len(text) <= 2000
                or any(not line.strip() for line in text.split("\n"))
                or re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text)):
            raise ValueError("Cue text must be nonempty bounded text without control characters or blank lines.")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise ValueError("Cue text must encode as valid UTF-8.") from None
        cues.append(Cue(start, end, text))
        previous_end = end
    return cues


def validate_exports(params):
    cues_from_arguments(params["cues"])
    for item in params["export_batch"]:
        cues_from_arguments(item["cues"])


def _stamp(seconds, *, ass=False):
    rate = 100 if ass else 1000
    ticks = round(seconds * rate)
    whole, fraction = divmod(ticks, rate)
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    if ass:
        return f"{hours}:{minutes:02}:{seconds:02}.{fraction:02}"
    return f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}"


def export_srt(directory, params, tracked_outputs):
    batches = [params["cues"], *[item["cues"] for item in params["export_batch"]]]
    counts = []
    for items in batches:
        cues = cues_from_arguments(items)
        content = "".join(f"{index}\n{_stamp(cue.start)} --> {_stamp(cue.end)}\n{cue.text}\n\n"
                          for index, cue in enumerate(cues, 1)).encode("utf-8")
        output = output_file(directory, "captions", ".srt")
        with output.open("xb") as handle:
            tracked_outputs.append(output)
            handle.write(content)
        counts.append(len(cues))
    return {"cue_counts": counts, "batch_size": len(batches), "encoding": "utf-8"}


def _text_file(path, maximum):
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("The finishing sidecar exceeds its bounded size limit.")
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError:
        raise ValueError("Finishing sidecars must contain valid UTF-8.") from None
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        raise ValueError("Finishing sidecars cannot contain control characters.")
    return text


def _time(value, *, ass=False):
    pattern = r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{2})" if ass else r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
    match = re.fullmatch(pattern, value.strip())
    if not match:
        raise ValueError("Subtitle timestamps must use the documented SRT or ASS format.")
    hours, minutes, seconds, fraction = map(int, match.groups())
    if minutes > 59 or seconds > 59:
        raise ValueError("Subtitle timestamps have invalid minutes or seconds.")
    return hours * 3600 + minutes * 60 + seconds + fraction / (100 if ass else 1000)


def _subtitle_text(text, *, ass=False):
    if ass:
        text = text.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")
    else:
        text = re.sub(r"</?(?:b|i|u)>", "", text, flags=re.IGNORECASE)
    if "\\" in text or "{" in text or "}" in text or re.search(r"</?font\b", text, re.IGNORECASE):
        raise ValueError("Subtitle font overrides, drawing commands and inline ASS tags are refused.")
    return text


def _srt(text):
    items = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not re.fullmatch(r"\d{1,4}", lines[0]):
            raise ValueError("SRT requires indexed timed-text blocks.")
        timing = lines[1].split(" --> ")
        if len(timing) != 2:
            raise ValueError("SRT requires one bounded start and end timestamp per cue.")
        items.append({"start": _time(timing[0]), "end": _time(timing[1]),
                      "text": _subtitle_text("\n".join(lines[2:]))})
    return cues_from_arguments(items)


def _ass(text):
    section = None
    styles = set()
    style_format = event_format = None
    items = []
    headers = {"scripttype", "playresx", "playresy", "wrapstyle", "scaledborderandshadow",
               "collisions", "timer"}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("["):
            if line not in {"[Script Info]", "[V4+ Styles]", "[Events]"}:
                raise ValueError("ASS supports Script Info, V4+ Styles and Events only; attachments are refused.")
            section = line
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError("ASS contains a malformed header or event.")
        key, value = key.strip().lower(), value.strip()
        if section == "[Script Info]":
            if key not in headers:
                raise ValueError("ASS contains unsupported script headers.")
            if key == "scripttype" and value != "v4.00+":
                raise ValueError("Only ASS v4.00+ is supported.")
        elif section == "[V4+ Styles]":
            if key == "format":
                style_format = tuple(part.strip().lower() for part in value.split(","))
                if style_format != _STYLE_FORMAT:
                    raise ValueError("ASS requires the standard V4+ style fields.")
            elif key == "style" and style_format is not None:
                values = [part.strip() for part in value.split(",")]
                if len(values) != len(_STYLE_FORMAT):
                    raise ValueError("ASS has a malformed style.")
                style = dict(zip(_STYLE_FORMAT, values))
                if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", style["name"])
                        or style["fontname"] not in {font[0] for font in FONTS.values()}):
                    raise ValueError("ASS Fontname must use an approved DejaVu family without paths or overrides.")
                for name in _STYLE_FORMAT[2:]:
                    value = style[name]
                    if "colour" in name:
                        if not re.fullmatch(r"&H[0-9A-Fa-f]{6,8}", value):
                            raise ValueError("ASS colours must be fixed hexadecimal values.")
                    elif not re.fullmatch(_FLOAT, value) or not math.isfinite(float(value)) or abs(float(value)) > 1000:
                        raise ValueError("ASS style values must be finite bounded numbers.")
                styles.add(style["name"])
            else:
                raise ValueError("ASS contains an unsupported style directive.")
        elif section == "[Events]":
            if key == "format":
                event_format = tuple(part.strip().lower() for part in value.split(","))
                if event_format != _EVENT_FORMAT:
                    raise ValueError("ASS requires standard Dialogue fields.")
            elif key in {"dialogue", "comment"} and event_format is not None:
                parts = value.split(",", 9)
                if len(parts) != 10:
                    raise ValueError("ASS contains a malformed Dialogue event.")
                event = dict(zip(_EVENT_FORMAT, parts))
                if (event["effect"].strip() or event["style"].strip() not in styles
                        or any(not re.fullmatch(r"\d{1,4}", event[name].strip())
                               for name in ("layer", "marginl", "marginr", "marginv"))):
                    raise ValueError("ASS effects and nonstandard event fields are refused.")
                if key == "dialogue":
                    items.append({"start": _time(event["start"], ass=True),
                                  "end": _time(event["end"], ass=True),
                                  "text": _subtitle_text(event["text"], ass=True)})
            else:
                raise ValueError("ASS contains an unsupported event directive.")
        else:
            raise ValueError("ASS requires a supported section header.")
    return cues_from_arguments(items)


def _subtitle(path):
    text = _text_file(path, _SUBTITLE_BYTES)
    if path.suffix.lower() == ".srt":
        return _srt(text)
    if path.suffix.lower() == ".ass":
        return _ass(text)
    raise ValueError("burn_subtitles accepts local .srt or restricted .ass timed text only.")


def _canonical_ass(cues, params, width, height):
    family, font_path = FONTS[params["font_id"]]
    if not font_path.is_file():
        raise ValueError("The selected DejaVu system font is missing on this local worker.")
    colour = params["colour"][1:]
    ass_colour = "&H00" + colour[4:6] + colour[2:4] + colour[0:2]
    style = (f"Default,{family},{params['font_size']},{ass_colour},&H000000FF,&H00000000,&H00000000,"
             f"0,0,0,0,100,100,0,0,1,{params['outline']:g},0,2,"
             f"{params['margin']},{params['margin']},{params['margin']},1")
    content = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\n"
               "ScaledBorderAndShadow: yes\nWrapStyle: 0\n[V4+ Styles]\nFormat: "
               + ", ".join(_STYLE_FORMAT) + "\nStyle: " + style + "\n[Events]\nFormat: "
               + ", ".join(_EVENT_FORMAT) + "\n")
    for cue in cues:
        if round(cue.end * 100) <= round(cue.start * 100):
            raise ValueError("Burned subtitles must remain positive after ASS centisecond rounding.")
        content += (f"Dialogue: 0,{_stamp(cue.start, ass=True)},{_stamp(cue.end, ass=True)},Default,,0,0,0,,"
                    + cue.text.replace("\n", r"\N") + "\n")
    encoded = content.encode("utf-8")
    if len(encoded) > 2 * 1024 * 1024:
        raise ValueError("Canonical subtitles exceed the bounded sidecar size.")
    return encoded, font_path.parent


def _filters(directory, names):
    from providers.ffmpeg.api import _bounded_run, _EXECUTION_DEADLINE

    binary = shutil.which("ffmpeg")
    if binary is None:
        raise ValueError("The local worker requires an installed ffmpeg with the requested finishing filters.")
    remaining = min(5, _EXECUTION_DEADLINE.get() - time.monotonic())
    if remaining <= 0:
        raise ValueError("Operation exceeded its hard timeout.")
    result = _bounded_run([binary, "-hide_banner", "-filters"], directory, remaining)
    delivery._complete(result)
    available = set(re.findall(r"^\s*[TSC.]{3}\s+(\w+)\s", result.stdout.decode("utf-8", errors="replace"), re.MULTILINE))
    if result.returncode or not names <= available:
        raise ValueError("The installed local ffmpeg build lacks required finishing filters.")


def _video_source(directory, source, *, audio=False):
    metadata, video, sound, metrics = delivery._delivery_source(directory, source, require_audio=audio)
    metrics["expected_video_codec"] = "h264"
    metrics["source_container_bitrate"] = metadata["format"].get("bit_rate")
    return metadata, video, sound, metrics


def _render(directory, source, video, metrics, *, vf=None, graph=None, prefix="finished",
            crf=None, preset="veryfast", sidecars=None):
    delivery._encoder(directory)
    output = output_file(directory, prefix, ".mp4")
    argv = _ffmpeg_input(directory, source) + ["-nostats"]
    argv += ["-filter_complex", graph, "-map", "[out]"] if graph else ["-vf", vf, "-map", "0:v:0"]
    argv += ["-map", "0:a:0?", "-c:v", "libx264", "-profile:v", "high", "-preset", preset,
             "-pix_fmt", "yuv420p", "-threads", str(THREADS)]
    bitrate = video.get("bit_rate") or metrics.get("source_container_bitrate")
    if crf is None and bitrate is not None:
        measured = int(bitrate)
        if not 0 < measured <= 200_000_000:
            raise ValueError("Source bitrate is outside the supported rendering range.")
        detail_floor = metrics["width"] * metrics["height"] * float(Fraction(metrics["source_fps"])) * .1
        target = math.ceil(max(measured * 1.25, detail_floor))
        argv += ["-b:v", str(target), "-maxrate", str(target * 2), "-bufsize", str(target * 4)]
        metrics["video_bitrate"] = target
    else:
        argv += ["-crf", str(18 if crf is None else crf)]
    if metrics["source_audio"]:
        argv += delivery._aac_args({"bitrate_kbps": 192})
    argv += ["-fps_mode", "passthrough", "-map_metadata", "-1", "-movflags", "+faststart",
             "-fs", str(MAX_OUTPUT_BYTES), "./" + output.name]
    return Command(argv, [output], metrics, sidecars=sidecars or {})


def burn_subtitles(directory, source, params):
    _filters(directory, {"ass"})
    items = [{"input_path": _input(directory, source)[2:], "subtitle_path": params["subtitle_path"]},
             *params["subtitle_batch"]]
    commands, artifacts = [], []
    for item in items:
        media = input_file(directory, item["input_path"])
        subtitle = input_file(directory, item["subtitle_path"])
        _, video, _, metrics = _video_source(directory, media)
        cues = _subtitle(subtitle)
        if cues[-1].end > metrics["source_duration"]:
            raise ValueError("Subtitle cues extend beyond the source duration.")
        content, fonts_dir = _canonical_ass(cues, params, metrics["width"], metrics["height"])
        sidecar = output_file(directory, "subtitles", ".ass")
        graph = f"ass=filename={_input(directory, sidecar)}:fontsdir={fonts_dir.as_posix()}"
        metrics.update(cue_count=len(cues), font_id=params["font_id"], input_path=item["input_path"])
        metrics["warnings"].append("Subtitle timestamps are rendered at ASS centisecond precision.")
        command = _render(directory, media, video, metrics, vf=graph, prefix="subtitled",
                          sidecars={sidecar: content})
        commands.append(command)
        artifacts.append(metrics)
    return [Command(command.argv, command.outputs, {"artifacts": artifacts},
                    command.stderr_bytes, command.sidecars) for command in commands]


def _cube(path):
    if path.suffix.lower() != ".cube":
        raise ValueError("LUT input must be a local .cube file.")
    size = None
    domains = {"DOMAIN_MIN": [0., 0., 0.], "DOMAIN_MAX": [1., 1., 1.]}
    seen = set()
    triples = []
    for raw in _text_file(path, _CUBE_BYTES).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0]
        if key in {"TITLE", "LUT_3D_SIZE", "DOMAIN_MIN", "DOMAIN_MAX"}:
            if key in seen or triples:
                raise ValueError("LUT headers must appear once before the numeric data.")
            seen.add(key)
            if key == "TITLE":
                if len(line) > 200 or not re.fullmatch(r'TITLE\s+"[^"\\]*"', line):
                    raise ValueError("LUT TITLE must be bounded quoted text.")
            elif key == "LUT_3D_SIZE":
                if len(parts) != 2 or not re.fullmatch(r"\d{1,2}", parts[1]) or not 2 <= int(parts[1]) <= 33:
                    raise ValueError("LUT_3D_SIZE must be an integer from 2 to 33.")
                size = int(parts[1])
            else:
                domains[key] = _triple(parts[1:])
        else:
            if size is None or len(triples) >= size ** 3:
                raise ValueError("LUT requires its bounded size header and exactly size cubed RGB triples.")
            triples.append(_triple(parts))
    if size is None or len(triples) != size ** 3:
        raise ValueError("LUT must contain exactly size cubed RGB triples.")
    if any(not 0 <= low < high <= 1 for low, high in zip(domains["DOMAIN_MIN"], domains["DOMAIN_MAX"])):
        raise ValueError("LUT domains must be ordered finite values inside 0 to 1.")
    content = f"LUT_3D_SIZE {size}\n"
    for key, values in domains.items():
        content += key + " " + " ".join(f"{value:.9g}" for value in values) + "\n"
    content += "".join(" ".join(f"{value:.9g}" for value in values) + "\n" for values in triples)
    return content.encode("ascii"), size


def _triple(parts):
    if len(parts) != 3 or any(len(value) > 64 or not re.fullmatch(_FLOAT, value) for value in parts):
        raise ValueError("LUT data requires three bounded numeric RGB values per line.")
    values = [float(value) for value in parts]
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError("LUT RGB values must be finite and inside 0 to 1.")
    return values


def color_match_lut(directory, source, params):
    _filters(directory, {"lut3d", "blend", "eq", "colorbalance"})
    _, video, _, metrics = _video_source(directory, source)
    sidecars = {}
    filters = []
    if params["lut_path"] is not None:
        lut = input_file(directory, params["lut_path"])
        content, size = _cube(lut)
        sidecar = output_file(directory, "grade", ".cube")
        sidecars[sidecar] = content
        filters.append(f"lut3d=file={_input(directory, sidecar)}:interp=tetrahedral")
        metrics.update(lut_size=size, lut_sha256=sha256_file(lut))
    contrast, saturation, red, blue = GRADE_PRESETS[params["grade_preset"]]
    filters += [f"eq=brightness={params['brightness']:g}:contrast={params['contrast'] * contrast:g}:"
                f"saturation={params['saturation'] * saturation:g}",
                f"colorbalance=rm={red:g}:bm={blue:g}", "format=gbrp"]
    graph = ("[0:v:0]format=gbrp,split[original][look];[look]" + ",".join(filters) + "[graded];"
             f"[graded][original]blend=all_mode=normal:all_opacity={params['intensity']:g}[out]")
    metrics.update(grade_preset=params["grade_preset"], intensity=params["intensity"])
    return [_render(directory, source, video, metrics, graph=graph, prefix="graded", sidecars=sidecars)]


def make_proxy(directory, source, params):
    _filters(directory, {"scale"})
    _, video, _, metrics = _video_source(directory, source)
    width, height = metrics["width"], metrics["height"]
    factor = min(1, params["height"] / height, (854 if params["height"] == 480 else 960) / width)
    fitted = [max(2, math.floor(value * factor / 2) * 2) for value in (width, height)]
    if abs(fitted[0] * height / (fitted[1] * width) - 1) > .01:
        raise ValueError("Source aspect ratio cannot fit the proxy bounds within 1% using even dimensions.")
    metrics.update(width=fitted[0], height=fitted[1], source_sha256=sha256_file(source), is_proxy=True,
                   requested_height=params["height"], crf=params["crf"], proxy_preset=params["proxy_preset"])
    metrics["warnings"].append("Proxy media is for editing; it is not a delivery master.")
    prefix = source.stem[:40] + f"-proxy-{params['height']}"
    return [_render(directory, source, video, metrics,
                    vf=f"scale={fitted[0]}:{fitted[1]}:flags=lanczos,setsar=1", prefix=prefix,
                    crf=params["crf"], preset=params["proxy_preset"])]


def audio_cleanup(directory, source, params):
    names = {"highpass", "afftdn", "equalizer"}
    if params["compressor"]:
        names.add("acompressor")
    _filters(directory, names)
    metadata, video, audio, duration = delivery._media(directory, source, audio=True)
    if len([stream for stream in metadata["streams"] if stream.get("codec_type") == "audio"]) != 1:
        raise ValueError("Audio cleanup requires exactly one intended audio stream.")
    rate, channels = int(audio.get("sample_rate", 0)), audio.get("channels")
    if not 8000 <= rate <= 192000 or not isinstance(channels, int) or not 1 <= channels <= 8:
        raise ValueError("Audio cleanup requires known sample rate and 1 to 8 channels.")
    graph = (f"highpass=f={params['highpass_hz']:g},afftdn=nr={params['denoise_db']:g}:"
             f"nf={CLEANUP_PRESETS[params['cleanup_preset']]},{EQ_PRESETS[params['eq_preset']]}")
    if params["compressor"]:
        threshold = 10 ** (params["compressor_threshold_db"] / 20)
        graph += f",acompressor=threshold={threshold:g}:ratio={params['compressor_ratio']:g}:attack=20:release=250:makeup=1"
    warnings = ["Cleanup changes loudness. Measure and normalize this cleaned output afterwards."]
    if video:
        _, _, _, metrics = _video_source(directory, source, audio=True)
        metrics["expected_video_codec"] = metrics["source_video_codec"]
        output = output_file(directory, "cleaned", ".mp4")
        argv = _ffmpeg_input(directory, source) + ["-nostats", "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                "-af", graph + f",atrim=duration={metrics['source_audio_duration']:g}", *delivery._aac_args({"bitrate_kbps": 192}),
                "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_OUTPUT_BYTES), "./" + output.name]
    else:
        output = output_file(directory, "cleaned", ".wav")
        metrics = {"source_duration": duration, "source_channels": channels, "source_sample_rate": rate,
                   "source_channel_layout": audio.get("channel_layout"), "audio_only": True}
        argv = _ffmpeg_input(directory, source) + ["-nostats", "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-af", graph, "-c:a", "pcm_s16le", "-ar", str(rate), "-map_metadata", "-1",
                "-fs", str(MAX_OUTPUT_BYTES), "./" + output.name]
    metrics.update(cleanup_preset=params["cleanup_preset"], eq_preset=params["eq_preset"],
                   compressor=params["compressor"], warnings=warnings, loudness_normalized=False)
    return [Command(argv, [output], metrics)]


def _finish_video(directory, source, params, output, metrics):
    if output.stat().st_size > MAX_OUTPUT_BYTES:
        raise ValueError("Finishing output exceeds its byte cap; FFmpeg size limits can overshoot buffered writes.")
    final = delivery.finish_delivery(directory, source, params, [output], metrics)
    if final["output_video_codec"] != metrics["expected_video_codec"]:
        raise ValueError("Finishing output changed the required video codec.")
    if metrics.get("is_proxy"):
        final["output_probe"] = delivery._execute(directory, "probe", output)
    return final


def finish_video(directory, source, params, outputs, metrics):
    if "artifacts" not in metrics:
        return _finish_video(directory, source, params, outputs[0], metrics)
    artifacts = []
    warnings = []
    for output, plan in zip(outputs, metrics["artifacts"]):
        final = _finish_video(directory, source, params, output, plan)
        artifacts.append({**plan, **final})
        warnings.extend(plan["warnings"])
    return {**artifacts[0], "artifacts": artifacts, "batch_size": len(artifacts), "warnings": warnings}


def finish_audio(directory, source, params, outputs, metrics):
    if not metrics.get("audio_only"):
        return finish_video(directory, source, params, outputs, metrics)
    _, video, audio, duration = delivery._media(directory, outputs[0], audio=True)
    if (video is not None or audio.get("codec_name") != "pcm_s16le"
            or audio.get("channels") != metrics["source_channels"]
            or int(audio.get("sample_rate", 0)) != metrics["source_sample_rate"]
            or (metrics["source_channel_layout"] and audio.get("channel_layout") != metrics["source_channel_layout"])
            or abs(duration - metrics["source_duration"]) > 1 / metrics["source_sample_rate"] + .000001):
        raise ValueError("Cleaned audio is incomplete or changed its duration, sample rate or channels.")
    return {"output_duration": duration, "output_audio_channels": audio["channels"],
            "output_sample_rate": int(audio["sample_rate"])}
