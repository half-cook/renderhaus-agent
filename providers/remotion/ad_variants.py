"""Local matrix worker. Human authorization is host context, never tool arguments."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time
import uuid
from typing import Any, Literal

from providers.remotion import api
from server.billing_rates import ad_matrix_estimate


LAYOUTS = json.loads(Path(__file__).with_name("ad_layouts.json").read_text())
REQUIRED = ("variant_key", "sku", "price_text", "cta_text", "logo_asset", "legal_text", "locale", "aspect")
OPTIONAL = ("product_asset", "vo_asset", "start_s", "end_s")
REFRAME_FIELDS = ("subject_box", "crop_box", "safe_zone", "anchor", "allow_upscale")
OPTIONAL += REFRAME_FIELDS + ("shots", "scene_times")
_AUTHORIZATION: ContextVar[tuple[str, str, str] | None] = ContextVar("ad_matrix_authorization", default=None)


@contextmanager
def authorize(stage: str, plan_hash: str, approved_by: str):
    """Called only by the host after a human decision or by the explicit operator CLI."""
    token = _AUTHORIZATION.set((stage, plan_hash, approved_by))
    try:
        yield
    finally:
        _AUTHORIZATION.reset(token)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_arguments(arguments: dict[str, Any]) -> None:
    if arguments.get("stage") not in {"plan", "render_first", "render_batch"}:
        raise ValueError("stage must be plan, render_first or render_batch.")
    if not isinstance(arguments.get("job_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", arguments["job_id"]):
        raise ValueError("job_id must contain 1-80 ASCII letters, digits, underscores or hyphens.")
    if not isinstance(arguments.get("brief"), dict):
        raise ValueError("brief must be an object.")
    if not isinstance(arguments.get("rows"), list) or not 1 <= len(arguments["rows"]) <= 100:
        raise ValueError("rows must contain 1-100 table records.")
    if type(arguments.get("concurrency", 2)) is not int or not 1 <= arguments.get("concurrency", 2) <= 2:
        raise ValueError("concurrency must be an integer from 1 to 2.")
    if not isinstance(arguments.get("master_asset"), str) or not arguments["master_asset"]:
        raise ValueError("master_asset must be a job-relative input file.")
    if not isinstance(arguments.get("plan_hash", ""), str) or (
        arguments.get("plan_hash") and not re.fullmatch(r"[0-9a-f]{64}", arguments["plan_hash"])
    ):
        raise ValueError("plan_hash must be the exact SHA-256 returned by plan.")


def _file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _media(job: Path, path: str) -> tuple[Path, dict[str, Any]]:
    from providers.ffmpeg.sandbox import input_file
    from providers.ffmpeg.api import execute

    resolved = input_file(job, path)
    result = execute("probe", job, path)
    if not result["ok"]:
        raise ValueError(result.get("error", "Asset probe failed."))
    return resolved, result["metrics"]


def _probe_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    # The free probe returns ffprobe's structured streams/format, never raw logs.
    return metrics.get("probe", metrics)


def _safe_dir(job: Path, name: str) -> Path:
    directory = job / name
    if directory.is_symlink():
        raise ValueError("Matrix output directories cannot be symlinks.")
    directory.mkdir(exist_ok=True)
    if directory.resolve().parent != job.resolve():
        raise ValueError("Matrix output must stay inside its job.")
    return directory


def _filename(row: dict, campaign: str) -> str:
    stem = f"{campaign[:16]}__{row['sku'][:16]}__{row['locale'][:16]}__{row['aspect'].replace(':', 'x')}__{digest(row['variant_key'])[:12]}__v1"
    if stem.startswith("-"):
        stem = "ad_" + stem
    return stem + ".mp4"


def reframe_shots(master: str, source_width: int, source_height: int, aspect: str,
                  shots: list[dict], *, rotation: int = 0, subject_box: dict | None = None,
                  crop_box: dict | None = None, safe_zone: dict | None = None,
                  anchor: str = "center", allow_upscale: bool = False,
                  target_size: tuple[int, int] | None = None, volume: float = 1,
                  fit: Literal["cover", "contain"] = "cover") -> tuple[list[dict], list[dict]]:
    """Compile one static validated window per shot into consecutive timeline clips."""
    from providers.ffmpeg.reframe import crop_plan, display_size, finite

    if not isinstance(shots, list) or not 1 <= len(shots) <= 60:
        raise ValueError("shots must contain 1-60 consecutive ranges.")
    previous = None
    for shot in shots:
        if not isinstance(shot, dict) or set(shot) - {"from_s", "to_s", "subject_box", "crop_box", "anchor"}:
            raise ValueError("Each shot accepts from_s, to_s and optional subject_box, crop_box, anchor.")
        start = finite(shot.get("from_s"), "from_s", 0, 600)
        end = finite(shot.get("to_s"), "to_s", 0, 600)
        if start >= end or previous is not None and not math.isclose(start, previous, abs_tol=1e-6):
            raise ValueError("Shot ranges must be positive and consecutive without gaps or overlap.")
        previous = end
    options = dict(rotation=rotation, subject_box=subject_box, crop_box=crop_box,
                   safe_zone=safe_zone, anchor=anchor, allow_upscale=allow_upscale)
    shot_options = [{**options, **{key: shot[key] for key in ("subject_box", "crop_box", "anchor") if key in shot}}
                    for shot in shots]
    plans = [crop_plan(source_width, source_height, aspect, target_size=target_size, **option)
             for option in shot_options]
    if fit == "contain":
        width, height = display_size(source_width, source_height, rotation)
        full_frame = {"x": 0, "y": 0, "width": width, "height": height}
        shot_options = [{**option, "subject_box": full_frame, "crop_box": None} for option in shot_options]
        plans = [crop_plan(source_width, source_height, aspect, target_size=target_size, **option)
                 for option in shot_options]
    common_size = (min(plan["width"] for plan in plans), min(plan["height"] for plan in plans))
    if any((plan["width"], plan["height"]) != common_size for plan in plans):
        plans = [crop_plan(source_width, source_height, aspect, target_size=common_size,
                           **option) for option in shot_options]
    visuals = []
    origin = shots[0]["from_s"]
    for shot, plan in zip(shots, plans, strict=True):
        plan.update(from_s=shot["from_s"], to_s=shot["to_s"])
        visual = {"kind": "video", "url": master, "start_seconds": shot["from_s"] - origin,
                  "source_in_seconds": shot["from_s"], "duration_seconds": shot["to_s"] - shot["from_s"],
                  "fit": "cover" if plan["mode"] == "crop" else "pad_blur", "volume": volume,
                  "reframe_size": {"width": plan["width"], "height": plan["height"]},
                  "allow_upscale": allow_upscale, "transition": "cut"}
        visual["crop_box" if plan["mode"] == "crop" else "pad_box"] = plan[
            "crop_box" if plan["mode"] == "crop" else "foreground_box"]
        visuals.append(visual)
    return visuals, plans


def _row_arguments(row: dict, brief: dict, job: Path, master: Path, source: dict) -> tuple[dict, list[dict]]:
    video = next(s for s in source["streams"] if s["codec_type"] == "video")
    duration = float(source["format"]["duration"])
    start, end = row.get("start_s", 0), row.get("end_s", duration)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or abs(v) > 600
           or not math.isfinite(v) for v in (start, end)):
        raise ValueError("start_s/end_s must be finite numbers.")
    if not 0 <= start < end <= duration or end - start > 600:
        raise ValueError("start_s/end_s must select at most 600 seconds inside the master.")
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
    from fractions import Fraction

    fps = float(Fraction(rate))
    if brief.get("fps", fps) != fps:
        raise ValueError("Flat-master fps differs from the brief/composition.")
    dimensions = api._media_dimensions(video)
    if dimensions is None:
        raise ValueError("The master's displayed dimensions could not be measured.")
    for name, measured in zip(("width", "height"), dimensions):
        if brief.get(f"source_{name}", measured) != measured:
            raise ValueError("Flat-master resolution differs from the brief/composition.")
    target_size = api.choose_canvas(row["aspect"], [dimensions], brief.get("output_resolution", "source"))
    options = {key: row.get(key, brief.get(key)) for key in REFRAME_FIELDS if key in row or key in brief}
    rotation = next((entry["rotation"] for entry in video.get("side_data_list", [])
                     if isinstance(entry, dict) and "rotation" in entry), (video.get("tags") or {}).get("rotate", 0))
    rotation = float(rotation)
    if not math.isfinite(rotation) or rotation % 90:
        raise ValueError("Master rotation must be a finite multiple of 90 degrees.")
    if "shots" in row and "scene_times" in row:
        raise ValueError("Choose shots or scene_times, not both.")
    if "scene_times" in row:
        from providers.ffmpeg.reframe import shots_from_scenes

        shots = shots_from_scenes(row["scene_times"], duration)
        shots = [{"from_s": max(start, shot["from_s"]), "to_s": min(end, shot["to_s"])}
                 for shot in shots if shot["to_s"] > start and shot["from_s"] < end]
    else:
        shots = row.get("shots", [{"from_s": start, "to_s": end}])
    visuals, plans = reframe_shots(str(master), video["width"], video["height"], row["aspect"], shots,
                                   rotation=int(rotation), target_size=target_size,
                                   volume=0 if row.get("vo_asset") else 1, fit=brief.get("fit", "cover"), **options)
    if not math.isclose(shots[0]["from_s"], start, abs_tol=1e-6) or not math.isclose(shots[-1]["to_s"], end, abs_tol=1e-6):
        raise ValueError("shots must cover the entire start_s/end_s master range.")
    width, height = plans[0]["width"], plans[0]["height"]
    safe = plans[0]["safe_zone"]
    x, y = width * safe["side"], height * safe["top"]
    box_width, box_height = width * (1 - 2 * safe["side"]), height * (1 - safe["top"] - safe["bottom"])
    length = end - start
    audio = [{"url": str(job / row["vo_asset"]), "duration_seconds": length, "fade_out_seconds": 0}] if row.get("vo_asset") else []
    if brief.get("reframe_only", False):
        return {"title": brief["campaign"], "visuals": visuals, "text_overlays": [], "audio_tracks": audio,
                "aspect_ratio": row["aspect"], "fps": fps,
                "output_resolution": brief.get("output_resolution", "source")}, plans
    logo = {"x": x, "y": y, "width": box_width * 0.25, "height": box_height * 0.15}
    visuals.append({"kind": "image", "url": str(job / row["logo_asset"]), "duration_seconds": length,
                    "track": 1, "fit": "contain", "box": logo})
    if row.get("product_asset"):
        visuals.append({"kind": "image", "url": str(job / row["product_asset"]), "duration_seconds": length,
                        "track": 2, "fit": "contain", "box": {"x": x + box_width * 0.55, "y": y,
                        "width": box_width * 0.4, "height": box_height * 0.17}})
    text = []
    for field, offset, size in (("sku", .20, .11), ("price_text", .36, .14),
                                ("cta_text", .56, .12), ("legal_text", .78, .08)):
        text.append({"text": row[field], "start_seconds": 0, "duration_seconds": length,
                     "box": {"x": x, "y": y + box_height * offset, "width": box_width, "height": box_height * .18},
                     "font_family": "dejavu-sans-bold" if field != "legal_text" else "dejavu-sans",
                     "min_font_size": 16, "max_font_size": min(180, max(16, int(height * size))),
                     "color": "#ffffff", "background_color": "#151515",
                     "fade_in_seconds": 0, "fade_out_seconds": 0})
    return {"title": brief["campaign"], "visuals": visuals, "text_overlays": text,
            "audio_tracks": audio, "aspect_ratio": row["aspect"], "fps": fps,
            "output_resolution": brief.get("output_resolution", "source")}, plans


def _plan(job: Path, master_asset: str, rows: list[dict], brief: dict) -> dict:
    planned, blocked = [], []
    brief = {"campaign": "campaign", "logo_alpha_required": True, **brief}
    if set(brief) - {"campaign", "logo_alpha_required", "legal_locales", "legal_by_locale", "fps",
                    "source_width", "source_height", "output_resolution", "fit", "reframe_only", *REFRAME_FIELDS}:
        raise ValueError("Brief contains unsupported fields; template/shell code is forbidden.")
    if brief.get("fit", "cover") not in {"cover", "contain"}:
        raise ValueError("fit must be cover or contain; contain preserves the whole master with blurred padding.")
    if (type(brief["logo_alpha_required"]) is not bool or type(brief.get("reframe_only", False)) is not bool
            or not isinstance(brief.get("legal_by_locale", {}), dict)
            or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip()
                   for k, v in brief.get("legal_by_locale", {}).items())
            or not isinstance(brief.get("legal_locales", []), list)
            or any(not isinstance(v, str) for v in brief.get("legal_locales", []))):
        raise ValueError("Brief requires boolean logo_alpha_required and valid locale legal rules.")
    campaign = brief["campaign"]
    if not isinstance(campaign, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", campaign):
        raise ValueError("campaign must be a safe ASCII filename identifier, at most 40 characters.")
    master, metadata = _media(job, master_asset)
    source = _probe_payload(metadata)
    if not any(s.get("codec_type") == "video" for s in source.get("streams", [])):
        raise ValueError("The master must contain readable video.")
    hashes = {master_asset: _file_hash(master)}
    source_video = next(s for s in source["streams"] if s.get("codec_type") == "video")
    tuples, keys = set(), set()
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or set(row) - set(REQUIRED + OPTIONAL):
                raise ValueError("Table row contains unsupported columns.")
            required = ("variant_key", "aspect") if brief.get("reframe_only", False) else REQUIRED
            missing = [key for key in required if not isinstance(row.get(key), str) or not row[key].strip()]
            if missing:
                raise ValueError("Missing or empty required cells: " + ", ".join(missing))
            if brief.get("reframe_only", False):
                row = {"sku": "master", "locale": "und", **row}
            for field in ("variant_key", "sku", "locale"):
                if not isinstance(row[field], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", row[field]):
                    raise ValueError(f"Unsafe {field}; use ASCII letters, digits, underscores or hyphens.")
            if row["aspect"] not in LAYOUTS:
                raise ValueError("aspect must be one of " + ", ".join(LAYOUTS) + ".")
            identity = (row["sku"], row["locale"], row["aspect"])
            if identity in tuples or row["variant_key"] in keys:
                raise ValueError("Duplicate (sku, locale, aspect) or variant_key.")
            tuples.add(identity)
            keys.add(row["variant_key"])
            legal = brief.get("legal_by_locale", {}).get(row["locale"])
            if legal is not None and legal != row["legal_text"]:
                raise ValueError("Legal line differs from the brief's verbatim locale rule.")
            for field in ("logo_asset", "product_asset", "vo_asset"):
                if not row.get(field):
                    continue
                path, metrics = _media(job, row[field])
                streams = _probe_payload(metrics).get("streams", [])
                kind = "audio" if field == "vo_asset" else "video"
                stream = next((s for s in streams if s.get("codec_type") == kind), None)
                if stream is None:
                    raise ValueError(f"{field} has no readable {kind} stream.")
                if field == "logo_asset" and brief["logo_alpha_required"]:
                    from PIL import Image

                    with Image.open(path) as image:
                        if "A" not in image.getbands() and "transparency" not in image.info:
                            raise ValueError("Logo alpha channel is required by the template.")
                hashes[row[field]] = _file_hash(path)
            arguments, reframe_plan = _row_arguments(row, brief, job, master, source)
            props = api.build_timeline_props(**arguments)
            if len(props["document"]["assets"]) > 60:
                raise ValueError("The matrix row exceeds the 60-asset local timeline limit; use fewer shots.")
            for asset in props["document"]["assets"]:
                asset["url"] = str(Path(asset["url"]).relative_to(job))
            for field in ("visuals", "audio_tracks"):
                for clip in arguments[field]:
                    clip["url"] = str(Path(clip["url"]).relative_to(job))
            planned.append({"row_index": index, **row, "timeline": props, "render_arguments": arguments,
                            "reframe_plan": reframe_plan,
                            "input_props_hash": digest(props), "filename": _filename(row, campaign),
                            "expected_strings": {} if brief.get("reframe_only", False) else
                            {field: row[field] for field in ("sku", "price_text", "cta_text", "legal_text")}})
        except (ValueError, OSError, KeyError, StopIteration) as exc:
            blocked.append({"row_index": index, "variant_key": row.get("variant_key") if isinstance(row, dict) else None,
                            "reasons": [str(exc)]})
    quote = ad_matrix_estimate({"stage": "plan", "rows": rows, "brief": brief})
    plan_hash = digest({"planned": planned, "blocked": blocked, "brief": brief,
                        "assets": hashes, "layouts": LAYOUTS, "estimate": quote})
    return {"status": "blocked" if blocked else "planned", "planned": planned, "blocked": blocked,
            "candidate_set": True, "review_note": "Reframing is editorial. These are candidates; a person must approve each aspect's contact sheet.",
            "asset_hashes": hashes,
            "plan_hash": plan_hash, "render_count": len(planned), "estimate": quote,
            "estimated_time_s": sum(p["timeline"]["renderConfig"]["durationInFrames"] /
                                    p["timeline"]["renderConfig"]["fps"] * 4 for p in planned),
            "source_resolution": "x".join(map(str, api._media_dimensions(source_video))) if api._media_dimensions(source_video) else None,
            "warnings": ["Safe-zone percentages are placeholders; confirm with the channel brief.",
                         "Flat-master swaps affect overlays only; baked-in pixels cannot change.",
                         "Delivery/loudness/black/freeze QC is pending feat/remotion-delivery-qc."]}


def approval_description(arguments: dict) -> str:
    quote = ad_matrix_estimate(arguments)
    aspects = sorted({r.get("aspect", "?") for r in arguments.get("rows", []) if isinstance(r, dict)})
    return (f"Approve {arguments.get('stage')}: {quote['render_count']} variants; aspects {', '.join(aspects)}; "
            f"plan hash {arguments.get('plan_hash') or 'missing; plan first'}. "
            f"Estimated cost ${quote['estimated_total_usd']:.4f} USD, including "
            f"${quote['estimated_license_usd']:.4f} operator licence allowance. {quote['assumptions']}")


def _save(path: Path, value: Any) -> None:
    if path.is_symlink():
        raise ValueError("Matrix state cannot be a symlink.")
    temporary = path.with_name("state_" + uuid.uuid4().hex + ".tmp")
    with temporary.open("x", encoding="utf-8") as target:
        json.dump(value, target, ensure_ascii=False, indent=2, allow_nan=False)
    temporary.replace(path)


def _freeze_sources(job: Path, directory: Path, hashes: dict[str, str]) -> dict[str, str]:
    from providers.ffmpeg.sandbox import input_file

    frozen = {}
    for source, expected in hashes.items():
        path = input_file(job, source)
        if _file_hash(path) != expected:
            raise ValueError("Input changed after planning; obtain a new plan and approval.")
        destination = directory / ("input_" + expected + path.suffix)
        if destination.is_symlink():
            raise ValueError("Frozen media cannot be a symlink.")
        if not destination.exists():
            with path.open("rb") as src, destination.open("xb") as target:
                shutil.copyfileobj(src, target)
            destination.chmod(0o400)
        if _file_hash(destination) != expected:
            raise ValueError("Input changed while freezing the approved media; re-plan.")
        frozen[source] = str(destination.relative_to(job))
    return frozen


def _load_manifest(path: Path, plan: dict, directory: Path) -> list[dict]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Matrix manifest is unsafe or too large.")
    entries = json.loads(path.read_text())
    if not isinstance(entries, list) or len(entries) > 100:
        raise ValueError("Matrix manifest must be a bounded list.")
    rows = {r["variant_key"]: r for r in plan["planned"]}
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("variant_key") not in rows:
            raise ValueError("Manifest contains an unplanned variant.")
        row = rows[entry["variant_key"]]
        if entry["variant_key"] in seen or any(entry.get(key) != row[key] for key in
                                              ("sku", "locale", "aspect", "input_props_hash")):
            raise ValueError("Manifest identity differs from the approved plan.")
        seen.add(entry["variant_key"])
        artifact = directory / row["filename"]
        if (entry.get("file") != str(artifact) or artifact.is_symlink() or not artifact.is_file()
                or not isinstance(entry.get("approved_by"), str) or not entry["approved_by"]
                or entry.get("sha256") != _file_hash(artifact)):
            raise ValueError("Manifest artifact is missing, changed or outside the matrix directory.")
    return entries


def _render(row: dict, job: Path, directory: Path, approved_by: str, review: bool) -> dict:
    from providers.ffmpeg.api import execute

    args = copy.deepcopy(row["render_arguments"])
    for field in ("visuals", "audio_tracks"):
        for clip in args[field]:
            clip["url"] = str(job / clip["url"])
    destination = directory / row["filename"]
    if destination.exists() or destination.is_symlink():
        raise ValueError("Existing output blocks this row; overwriting is forbidden.")
    attempt = directory / ("attempt_" + digest(row["variant_key"])[:24] + ".json")
    if attempt.exists() or attempt.is_symlink():
        raise ValueError("This variant was already attempted. Reconcile the saved job; blind retries are forbidden.")
    _save(attempt, {"variant_key": row["variant_key"], "status": "starting"})
    result = api.render_timeline(**args, output_filename=row["filename"])
    _save(attempt, {"variant_key": row["variant_key"], "status": result["status"],
                    "render_id": result.get("render_id")})
    deadline = time.monotonic() + 1200
    while result.get("status") in {"queued", "running", "preparing"}:
        if time.monotonic() >= deadline:
            raise ValueError("Local render timed out; reconcile the saved render before retrying.")
        time.sleep(.1)
        result = api.get_render_progress(render_id=result["render_id"], bucket_name="local")
    if result.get("status") != "succeeded":
        raise ValueError(result.get("error") or f"Render ended with status {result.get('status')}.")
    with Path(result["output_path"]).open("rb") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target)
    entry = {key: row[key] for key in ("variant_key", "sku", "locale", "aspect", "input_props_hash")}
    config = row["timeline"]["renderConfig"]
    entry.update({"composition": "RenderhausTimeline", "template_id": "ad-matrix-v1",
                  "file": str(destination), "output_path": str(destination), "sha256": _file_hash(destination),
                  "duration_s": config["durationInFrames"] / config["fps"],
                  "qc": {"text_fit": "passed", "safe_zone": "passed", "delivery_qc": "pending"},
                  "ocr_match": None, "approved_by": approved_by, "editorial_review": "pending",
                  "reframe_plan": row["reframe_plan"],
                  **{key: result.get(key) for key in ("width", "height", "source_resolution", "upscaled", "warnings")}})
    duration = entry["duration_s"]
    sheet = execute("contact_sheet", job, str(destination.relative_to(job)),
                    {"every_s": max(.1, duration / 3), "cols": 3, "rows": 1})
    if not sheet["ok"]:
        raise ValueError(sheet.get("error", "Contact sheet failed."))
    entry.update(contact_sheet=sheet["outputs"][0]["path"],
                 review_assets=[{"output_path": output["path"]} for output in sheet["outputs"]])
    if review:
        frames = execute("extract_frames", job, str(destination.relative_to(job)),
                         {"times": [duration * .05, duration * .5, max(0, duration - 1 / config["fps"])], "width": min(1920, config["width"])})
        if not frames["ok"]:
            raise ValueError(frames.get("error", "Review frame extraction failed."))
        entry.update(review_frames=[o["path"] for o in frames["outputs"]],
                     contact_sheet=sheet["outputs"][0]["path"], expected_strings=row["expected_strings"],
                     review_assets=[{"output_path": o["path"]} for o in frames["outputs"] + sheet["outputs"]])
    return entry


def render_ad_variants(stage: Literal["plan", "render_first", "render_batch"], job_id: str,
                       brief: dict, rows: list[dict], master_asset: str,
                       plan_hash: str = "", concurrency: int = 2) -> dict:
    """Plan a local retail matrix, approve first-aspect samples, then approve the bound batch."""
    args = dict(stage=stage, job_id=job_id, brief=brief, rows=rows, master_asset=master_asset,
                plan_hash=plan_hash, concurrency=concurrency)
    validate_arguments(args)
    if api.render_backend() != "local":
        return {"status": "blocked", "reason": "Ad matrices require the local/worker backend with the job directory and ffmpeg. Lambda matrix orchestration is not available; existing render_timeline remains supported."}
    from providers.ffmpeg.sandbox import job_directory

    try:
        job = job_directory(job_id)
        plan = _plan(job, master_asset, rows, brief)
    except (ValueError, OSError, KeyError) as exc:
        return {"status": "blocked", "reason": str(exc), "planned": [], "blocked": [{"reasons": [str(exc)]}]}
    if stage == "plan":
        return plan
    authorization = _AUTHORIZATION.get()
    if not authorization or authorization[:2] != (stage, plan_hash) or not authorization[2]:
        return {"status": "blocked", "reason": "Explicit human approval is required for this render stage."}
    if plan["blocked"] or not plan_hash or plan_hash != plan["plan_hash"]:
        return {**plan, "status": "blocked", "reason": "Plan changed or contains blocked rows. Re-plan and obtain new approval."}
    if api.dry_run():
        return {"status": "dry_run", "plan_hash": plan_hash, "estimate": ad_matrix_estimate(args), "rendered": []}
    directory = _safe_dir(job, "ad_matrix_" + plan_hash[:24])
    lock = directory / "worker.lock"
    if lock.is_symlink():
        return {"status": "blocked", "reason": "Matrix lock cannot be a symlink."}
    try:
        fd = os.open(lock, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("Matrix lock must be a regular file.")
    except (ValueError, OSError) as exc:
        return {"status": "blocked", "reason": str(exc)}
    with os.fdopen(fd, "a") as lockfile:
        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "blocked", "reason": "This matrix is already running; inspect its manifest."}
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink():
            return {"status": "blocked", "reason": "Manifest cannot be a symlink."}
        try:
            rendered = _load_manifest(manifest_path, plan, directory)
            frozen = _freeze_sources(job, directory, plan["asset_hashes"])
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return {"status": "blocked", "reason": str(exc)}
        first_key = (plan["planned"][0]["sku"], plan["planned"][0]["locale"])
        first = [r for r in plan["planned"] if (r["sku"], r["locale"]) == first_key]
        completed = {r["variant_key"] for r in rendered if Path(r["file"]).is_file()
                     and _file_hash(Path(r["file"])) == r["sha256"]}
        if stage == "render_batch" and not {r["variant_key"] for r in first} <= completed:
            return {"status": "blocked", "reason": "Render and inspect the first variant at every aspect before batch approval."}
        selected = first if stage == "render_first" else [r for r in plan["planned"] if r not in first]
        selected = [r for r in selected if r["variant_key"] not in completed]
        failed = []

        def run(row):
            try:
                frozen_row = copy.deepcopy(row)
                for field in ("visuals", "audio_tracks"):
                    for clip in frozen_row["render_arguments"][field]:
                        clip["url"] = frozen[clip["url"]]
                return _render(frozen_row, job, directory, authorization[2], stage == "render_first"), None
            except (ValueError, OSError, RuntimeError) as exc:
                return None, {"variant_key": row["variant_key"], "reasons": [str(exc)]}

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for entry, error in pool.map(run, selected):
                if entry:
                    rendered.append(entry)
                else:
                    failed.append(error)
                _save(manifest_path, rendered)
        if not manifest_path.exists():
            _save(manifest_path, rendered)
        _save(directory / "report.json", {"planned": plan["render_count"], "rendered": len(rendered),
                                          "blocked": plan["blocked"], "failed": failed})
        return {"status": "failed" if failed else "succeeded", "plan_hash": plan_hash,
                "candidate_set": True, "review_note": plan["review_note"],
                "planned": plan["render_count"], "rendered": rendered, "blocked": plan["blocked"],
                "failed": failed, "manifest_path": str(manifest_path), "warnings": plan["warnings"],
                "estimate": ad_matrix_estimate(args)}
