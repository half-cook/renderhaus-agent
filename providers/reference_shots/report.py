from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import re
import shutil

from providers.reference_shots.analysis import (
    Budget, HIGH_MOTION, MAX_EMBED_BYTES, NEAR_ZERO_MOTION, load_measurements,
    new_bundle, output_records, write_json,
)
from providers.reference_shots.contracts import Measurements, PinnedFile, ReportParams, ShotLabel


LABEL_FIELDS = ("shot_size", "category", "camera_move", "frame_description", "rhythm_role")
UNKNOWN = re.compile(r"^(?:unknown|uncertain|unsure|unavailable|unclassified|undetermined|n/?a|"
                     r"not visible|cannot determine|not enough evidence)(?:\b|$)", re.IGNORECASE)


def _rows_and_gates(manifest: Measurements, labels: list[ShotLabel] | None) -> tuple[list[dict], list[str], list[str], list[int]]:
    if labels is None:
        labels = [ShotLabel(shot_id=shot.shot_id, **dict.fromkeys(LABEL_FIELDS, "unknown")) for shot in manifest.shots]
    by_id = {item.shot_id: item for item in labels}
    expected = {shot.shot_id for shot in manifest.shots}
    if len(by_id) != len(labels) or set(by_id) != expected:
        raise ValueError("Visual labels must cover every measured shot exactly once, with no missing or duplicate ids.")
    rows, failures, warnings, incomplete = [], [], list(manifest.warnings), []
    for shot in manifest.shots:
        label = by_id[shot.shot_id]
        rows.append({**shot.model_dump(), **label.model_dump()})
        if any(UNKNOWN.match(getattr(label, field)) for field in LABEL_FIELDS):
            incomplete.append(shot.shot_id)
        if label.camera_move not in {'static', 'unknown'}:
            if shot.median_frame_difference is None:
                failures.append(f"Shot {shot.shot_id}: moving-camera claim cannot be checked because within-shot motion is unknown.")
            elif shot.median_frame_difference <= NEAR_ZERO_MOTION:
                failures.append(f"Shot {shot.shot_id}: moving-camera claim conflicts with near-zero measured motion.")
        elif (label.camera_move == 'static' and shot.median_frame_difference is not None
              and shot.median_frame_difference >= HIGH_MOTION):
            warnings.append(f"Shot {shot.shot_id}: high measured motion with a static camera label; subject motion may explain it.")
    return rows, failures, warnings, incomplete


def _read_evidence(directory: Path, record: PinnedFile, maximum: int) -> bytes:
    with (directory / record.path).open("rb") as source:
        data = source.read(maximum + 1)
    if (len(data) > maximum or len(data) != record.bytes
            or hashlib.sha256(data).hexdigest() != record.sha256):
        raise ValueError("An embedded evidence checksum changed or exceeded its byte cap.")
    return data


def _csv_text(value: str) -> str:
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _csv(rows: list[dict], provenance: str, blocked: bool) -> bytes:
    stream = io.StringIO(newline="")
    fields = ["shot_id", "start_s", "end_s", "duration_s", "median_frame_difference",
              *LABEL_FIELDS, "labels_provenance", "semantic_review", "status"]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        values = {name: row[name] for name in fields if name in row}
        values.update({name: f"{row[name]:.2f}" for name in ("start_s", "end_s", "duration_s")})
        values.update({name: _csv_text(row[name]) for name in LABEL_FIELDS})
        values.update(labels_provenance=provenance, semantic_review="pending_visual_review",
                      status="blocked" if blocked else "incomplete")
        writer.writerow(values)
    data = stream.getvalue().encode("utf-8")
    if len(data) > 256 * 1024:
        raise ValueError("The shot CSV exceeded its bounded size.")
    return data


def _html(directory: Path, manifest: Measurements, payload: dict, budget: Budget) -> bytes:
    media = base64.b64encode(_read_evidence(directory, manifest.player, MAX_EMBED_BYTES)).decode("ascii")
    budget.remaining()
    rows = payload["shots"]
    table = []
    pace = []
    for row in rows:
        start = json.dumps(row["start_s"], allow_nan=False)
        table.append(
            f'<tr data-shot="{row["shot_id"]}" data-start="{start}" tabindex="0" role="button" '
            f'aria-label="Play shot {row["shot_id"]}"><th scope="row">{row["shot_id"]}</th>'
            f'<td><button type="button" class="time">{row["start_s"]:.2f}s</button><br>'
            f'<span class="muted">to {row["end_s"]:.2f}s</span></td><td>{row["duration_s"]:.2f}s</td>'
            f'<td>{html.escape(row["shot_size"])}</td><td>{html.escape(row["category"])}</td>'
            f'<td>{html.escape(row["camera_move"])}</td><td>{html.escape(row["frame_description"])}</td>'
            f'<td>{html.escape(row["rhythm_role"])}</td><td>{"unknown" if row["median_frame_difference"] is None else format(row["median_frame_difference"], ".5f")}</td></tr>')
        pace.append(f'<button type="button" data-shot="{row["shot_id"]}" data-start="{start}" '
                    f'style="flex-grow:{row["duration_s"]:.12g}" '
                    f'aria-label="Shot {row["shot_id"]}, {row["duration_s"]:.2f} seconds" '
                    f'title="Shot {row["shot_id"]}: {row["duration_s"]:.2f}s">{row["shot_id"]}</button>')
    sheets = []
    for index, sheet in enumerate(manifest.contact_sheets, 1):
        encoded = base64.b64encode(_read_evidence(directory, sheet, 2 * 1024 * 1024)).decode("ascii")
        sheets.append(f'<figure><img src="data:image/jpeg;base64,{encoded}" '
                      f'alt="Sheet {index}, paired measured keyframes for shots {", ".join(map(str, sheet.shot_ids))}">'
                      f'<figcaption>Contact sheet {index}. Two frames per shot at 15% and 85%.</figcaption></figure>')
    failures = "".join(f"<li>{html.escape(value)}</li>" for value in payload["gate_failures"])
    warnings = "".join(f"<li>{html.escape(value)}</li>" for value in payload["warnings"])
    stats = payload["stats"]
    label_note = ("Simulated visual labels. Semantic review remains pending." if payload["labels_provenance"] == "simulated"
                  else "Visual labels are unverified. Semantic review remains pending.")
    if payload["phase"] == "measured":
        label_note = "Timing and motion are measured. Visual labels are unknown and await review."
    status = "Blocked" if failures else "Incomplete"
    checks = "Some deterministic checks failed." if failures else "Deterministic timing and motion checks passed."
    timeline = json.dumps([{"id": row["shot_id"], "start": row["start_s"], "end": row["end_s"]}
                           for row in rows], allow_nan=False, separators=(",", ":"))
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; media-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Reference shot breakdown</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f3ec;color:#182b2b;font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1440px;margin:auto;padding:32px}}h1{{font-size:clamp(28px,4vw,48px);line-height:1.1;margin:8px 0 16px}}
h2{{margin-top:32px}}.eyebrow{{letter-spacing:.12em;font-size:12px;text-transform:uppercase}}.muted,figcaption{{color:#526565;font-size:13px}}
.notice{{border-left:4px solid #b66b20;padding:12px 18px;background:#fff5db;margin:24px 0}}.notice p{{margin:4px 0}}
video{{display:block;width:100%;max-height:600px;background:#101919;border-radius:8px}}.stats{{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}}
.stats div{{background:white;padding:14px 20px;border:1px solid #d4ded6;min-width:170px}}.stats strong{{display:block;font-size:26px}}
#pace-strip{{display:flex;gap:3px;width:100%;height:48px;margin:12px 0 24px}}button{{font:inherit;cursor:pointer}}
#pace-strip button{{flex-basis:0;min-width:7px;overflow:hidden;padding:0;background:#315c57;color:white;border:0}}
#pace-strip button:nth-child(even){{background:#537c72}}#pace-strip button.active{{background:#aa571a;outline:2px solid #182b2b;outline-offset:1px}}
.table-wrap{{overflow:auto;border:1px solid #c9d5cd}}table{{border-collapse:collapse;width:100%;min-width:1050px;background:white;text-align:left}}
th,td{{padding:12px;border-bottom:1px solid #dce3dc;vertical-align:top}}thead{{background:#e2e9df}}tbody tr{{cursor:pointer}}
tbody tr.active{{background:#fff0ca}}tbody tr:hover{{background:#f0f5e9}}tbody tr:focus{{outline:3px solid #315c57;outline-offset:-3px}}
.time{{border:0;background:none;padding:0;color:#235f61;text-decoration:underline}}figure{{margin:24px 0}}figure img{{max-width:100%;height:auto;border-radius:6px}}
@media(max-width:700px){{main{{padding:20px 14px}}.stats{{gap:8px}}.stats div{{min-width:140px;flex:1}}}}
</style></head><body><main><div class="eyebrow">Measured reference film</div><h1>Reference shot breakdown</h1>
<p>Source picture {manifest.source.width} × {manifest.source.height}. Duration {manifest.source.duration_s:.2f}s. Timings below are measured from this film.</p>
<div class="notice" role="status"><strong>{status}. Visual review pending.</strong><p>{label_note}</p><p>{checks}</p></div>
<video id="reference-player" controls playsinline preload="metadata" src="data:video/mp4;base64,{media}" aria-label="Reference film"></video>
<p class="muted">{("Compressed review preview" if manifest.player.kind == "proxy" else "Embedded source picture")} at {manifest.player.width} × {manifest.player.height}. Click a shot or a pace segment to play from its measured start.</p>
<div class="stats"><div>Shots<strong>{stats["shot_count"]}</strong></div><div>Average shot<strong>{stats["average_shot_s"]:.2f}s</strong></div><div>Cuts per minute<strong>{stats["cuts_per_minute"]:.2f}</strong></div></div>
<h2>Pace</h2><div id="pace-strip" aria-label="Shot duration pace strip">{"".join(pace)}</div>
<h2>Shot list</h2><p class="muted">Timing and motion columns contain measurements. The remaining columns contain visual labels awaiting semantic review. Motion is normalized from 0 to 1.</p>
<div class="table-wrap"><table><thead><tr><th>Shot</th><th>Measured time</th><th>Duration</th><th>Shot size</th><th>Category</th><th>Camera move</th><th>Frame description</th><th>Rhythm role</th><th>Median frame difference</th></tr></thead><tbody>{"".join(table)}</tbody></table></div>
{("<h2>Failed checks</h2><ul>" + failures + "</ul>") if failures else ""}
<h2>Notes</h2><ul>{warnings}</ul><h2>Paired keyframes</h2>{"".join(sheets)}
</main><script>
const timeline={timeline};
const player=document.getElementById('reference-player');
const elements=Array.from(document.querySelectorAll('[data-shot]'));
function highlight(){{const t=player.currentTime;const shot=timeline.find(s=>t>=s.start&&t<s.end)||timeline[timeline.length-1];for(const el of elements){{const active=Number(el.dataset.shot)===shot.id;el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','true');else el.removeAttribute('aria-current');}}}}
for(const el of elements){{const seek=()=>{{player.currentTime=Number(el.dataset.start);highlight();player.play().catch(()=>{{}});}};el.addEventListener('click',seek);if(el.tagName==='TR')el.addEventListener('keydown',event=>{{if(event.key==='Enter'||event.key===' '){{event.preventDefault();seek();}}}});}}
player.addEventListener('timeupdate',highlight);player.addEventListener('seeked',highlight);player.addEventListener('loadedmetadata',highlight);highlight();
</script></body></html>'''
    data = document.encode("utf-8")
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("The self-contained review report exceeded its 16 MiB cap.")
    budget.remaining()
    return data


def export_report(directory: Path, bundle: Path, manifest: Measurements, labels: list[ShotLabel] | None,
                  provenance: str, budget: Budget) -> dict:
    rows, failures, warnings, incomplete = _rows_and_gates(manifest, labels)
    stats = {"shot_count": len(rows), "cut_count": len(rows) - 1,
             "duration_s": manifest.source.duration_s,
             "average_shot_s": manifest.source.duration_s / len(rows),
             "cuts_per_minute": (len(rows) - 1) * 60 / manifest.source.duration_s}
    payload = {"schema_version": 1, "phase": "measured" if labels is None else "labeled",
               "status": "blocked" if failures else "incomplete", "gates_passed": not failures,
               "semantic_review": "pending_visual_review", "labels_provenance": provenance,
               "incomplete_shot_ids": incomplete, "gate_failures": failures, "warnings": warnings,
               "source": manifest.source.model_dump(), "stats": stats, "shots": rows,
               "contact_sheets": [sheet.model_dump() for sheet in manifest.contact_sheets],
               "player": manifest.player.model_dump()}
    budget.remaining()
    page = _html(directory, manifest, payload, budget)
    csv_data = _csv(rows, provenance, bool(failures))
    paths = {"shots_path": bundle / "shots.json", "csv_path": bundle / "shots.csv",
             "report_path": bundle / "report.html"}
    write_json(paths["shots_path"], payload, limit=512 * 1024)
    for path, data in ((paths["csv_path"], csv_data), (paths["report_path"], page)):
        with path.open("xb") as output:
            output.write(data)
    return {"ok": not failures, **{key: value for key, value in payload.items() if key != "shots"},
            **{key: str(value) for key, value in paths.items()}, "outputs": output_records(list(paths.values()))}


def build_report(directory: Path, input_path: str, params: ReportParams, budget: Budget) -> dict:
    manifest = load_measurements(directory, input_path, params.measurements_sha256 or "")
    _rows_and_gates(manifest, params.labels)
    budget.remaining()
    bundle = new_bundle(directory, "report")
    try:
        result = export_report(directory, bundle, manifest, params.labels, params.labels_provenance, budget)
        load_measurements(directory, input_path, params.measurements_sha256 or "")
        budget.remaining()
        return {**result, "analysis_path": str(directory / input_path) if not Path(input_path).is_absolute() else input_path}
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        raise
