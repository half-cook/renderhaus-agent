# NLE timeline export

`Remotion___export_nle_timeline` exports a pinned Renderhaus Remotion assembly for an editor.
The zip contains `timeline.otio`, `timeline.fcpxml`, one CMX3600 EDL per track, a provenance
manifest, and the referenced media. OpenTimelineIO is the primary representation and uses
the `opentimelineio` Python package. FCPXML is the second export intended for Resolve import.
No part of the exporter launches or controls Resolve.

FCPXML is different from Final Cut Pro 7 XML, the `xmeml` dialect commonly used with Premiere.
This implementation exports FCPXML, not `xmeml`. Direct Premiere import and Resolve import
remain untested. FCPXML structural checks and an OTIO round trip do not prove NLE compatibility.

## Gateway contract

The tool follows the existing Remotion provider registry, shared argument validation, and
committed Gateway schema. No separate agent tool registration is required.

| Argument | Type | Meaning |
| --- | --- | --- |
| `timeline_json` | string, required | JSON-encoded Remotion `document` and `renderConfig` with immutable media metadata. |
| `output_filename` | string | Requested zip filename, sanitized by the provider. Defaults to `renderhaus-handoff.zip`. |

The tool exports the supplied assembly snapshot. It does not infer an edit from canvas positions
or read an editor's Resolve project. Studio does not yet retain source timecode, reel, and full
provenance in its public asset reference. The caller supplies those fields in the snapshot.
Missing metadata is an error. Export does not incur the Remotion render generation charge.

`REMOTION_DRY_RUN=true` returns `status=dry_run` without exporting files. A dry-run result
does not constitute a handoff. Local export creates a zip under ignored `.renderhaus/media/`.
The Gateway Lambda uploads the completed zip to its configured output bucket and returns a
download URL. ZIPs are handoff artifacts, not Studio image, video, or audio canvas nodes.

## Assembly snapshot

The document uses the same `assets`, `tracks`, and clip timing shape as the Remotion renderer.
Each referenced asset requires these additional fields.

| Asset field | Meaning |
| --- | --- |
| `versionId` | Immutable version identity, separate from the media URL. |
| `checksum` | SHA-256 of the complete source file. Export verifies the packaged bytes. |
| `sourceTimecode` | Timecode of the first source frame, including `;` for drop-frame. |
| `reelName` | Original reel name, retained in OTIO, FCPXML metadata, and the manifest. |
| `provenance` | Nonempty JSON object describing origin and parent version identities. |
| `generated` | Explicit boolean identifying generated footage. |
| `durationSec` | Complete media duration, including frames outside the selected trim. |
| `hasAudio` | Required boolean for video. Audio assets have audio by default; images cannot have audio. |

The existing Studio argument transformation resolves `renderhaus-asset://<version-id>`
inside `timeline_json` to a provider-reachable URL. `versionId` remains a separate identifier.
The export retains identity and provenance rather than temporary URLs in its interchange files.

A minimal snapshot has this shape.

```json
{
	"document": {
		"id": "project-1",
		"name": "Editor handoff",
		"assets": [{
			"id": "camera-1",
			"name": "Camera A",
			"kind": "video",
			"hasAudio": true,
			"url": "renderhaus-asset://version-camera-1",
			"versionId": "version-camera-1",
			"checksum": "<64 hexadecimal SHA-256 characters>",
			"sourceTimecode": "01:00:00:00",
			"reelName": "CAMERA_A",
			"provenance": {"origin": "upload"},
			"generated": false,
			"durationSec": 20
		}],
		"tracks": [{
			"id": "v1",
			"name": "Camera",
			"kind": "video",
			"items": [{
				"id": "clip-1",
				"type": "clip",
				"assetId": "camera-1",
				"start": 0,
				"duration": 5,
				"sourceIn": 2
			}]
		}]
	},
	"renderConfig": {
		"fps": 24,
		"dropFrame": false,
		"timecode": "01:00:00:00",
		"width": 1920,
		"height": 1080,
		"durationInFrames": 120
	}
}
```

The source in-point is `sourceTimecode + sourceIn`, independent of the sequence's record
timecode. OTIO's available range begins at the source timecode. Its clip source range begins
at the trimmed source timecode. FCPXML uses rational seconds and source-start resource times.
Rates include 24, 25, and exact `30000/1001`; drop-frame skips labels, not media frames.

## Track and package behavior

The exporter retains original tracks, including empty tracks. It moves generated clips to
new tracks above existing video tracks and to separate new audio tracks. It never places
generated clips on an original export track. The snapshot itself is unchanged.

CMX3600 cannot encode the full layered edit in one list. The archive includes separate EDLs
under `edl/`, including reserved empty tracks. EDL reel tokens fit eight characters. Where a
full reel cannot fit, the exporter assigns an alias and retains the original reel in comments
and the manifest. Record and source out-points are exclusive.

OTIO references and FCPXML media resources use relative paths into `media/`.
Extract the whole zip before import and retain its folder structure. Relink to the extracted
`media/` folder if an NLE asks for a media root. An importer may not resolve relative paths
automatically; that behavior needs a real round trip.

Import as a new timeline for review. When transferring generated tracks to an existing graded
timeline, add new destination tracks above the existing picture tracks. Export track isolation
does not control an editor's import options or guarantee that an NLE preserves an existing grade.

## Offline verification and limits

Run the focused suite with `.venv/bin/python -m unittest discover -s tests -p test_nle_export.py`.
Golden files live under `tests/golden/nle/`. The media fixtures are small, valid MP4 files.
The suite reads exported OTIO through the Python adapter, compares timecode golden files at
24, 25, and 29.97 drop-frame, and checks FCPXML resources, timing, and connected clip structure.
It also checks generated track isolation, media integrity, and rejected inputs.
FCPXML tests validate the exported structure and references. They are not a Resolve import test.
Regenerate goldens with `.venv/bin/python tests/update_nle_goldens.py` and review the resulting diff.
Local Gateway dispatch exercises the complete exporter. Lambda delivery tests use an offline S3
stub and verify the uploaded zip bytes; they do not prove live bucket delivery.

The exporter handles media edits with supported timing. Unsupported edits cause an error
rather than a silent approximation. It does not render Remotion titles, motion, effects,
or retimes into replacement media. Source frame rate and timecode must match the assembly's
rate and drop-frame mode for this handoff. Clip windows use Remotion's rounded end minus rounded
start, including subframe edit positions. Explicit `sourceOut` must agree with that frame window.
FCPXML omits optional source channel and sample-rate declarations so it does not invent them.
Zero gain mutes video audio through `srcEnable=video`, or disables an audio-only clip.
CMX3600 gain omission is reported as a warning.

The Gateway accepts snapshots up to 2 MiB. Export limits are 128 MiB per media file and 384 MiB
of referenced media per archive. Local files must remain under the configured Renderhaus media
roots. Remote sources must use an exact allowed virtual-host S3 hostname for
`REMOTION_APP_BUCKET_NAME`, `PROVIDER_INPUT_BUCKET`, or `AWS_S3_BUCKET`, in the configured region.
Only HTTPS on port 443 is accepted. Redirects and nonpublic DNS addresses are rejected.
Lambda delivery requires `REMOTION_APP_BUCKET_NAME` as its output bucket. Embedded provenance
URLs lose credentials, query strings, and fragments; credential fields are omitted.

Live media retrieval, bucket delivery, browser E2E,
and actual Resolve or Premiere round trips have not been performed for this change.

AAF is unimplemented and untested. AAF support is pending a real Resolve round trip.
A future local bridge could use Resolve Studio scripting on the editor's machine to import
the handoff onto new tracks. File-based re-import is implemented below; live editor control remains future work.

The design was informed by FilmCraft's interchange implementation at
`/workspace/filmcraft/crates/interchange`, especially its EDL, FCP7 XML, FCPXML, and OTIO modules.
No reference source code was copied verbatim.

## Import an editor's timeline

`Remotion___import_nle_timeline` is the inverse file-based path. It imports one project
sequence from FCPXML 1.9, 1.10, or 1.11, or one OpenTimelineIO JSON Timeline. Supply the
XML text itself, including `Info.fcpxml` from an `.fcpxmld` bundle. ZIP, AAF, CMX3600 EDL,
and Final Cut Pro 7 `xmeml` import are unsupported.

| Argument | Type | Meaning |
| --- | --- | --- |
| `interchange_text` | string, required | Editor's FCPXML or OTIO JSON contents, at most 2 MiB UTF-8. |
| `timeline_json` | string, required | Current Renderhaus `document`/`renderConfig` assembly envelope, at most 2 MiB. |
| `format` | string | `fcpxml` by default, or `otio`. |

Current assets need unique `id`, `kind`, `url`, and full source `durationSec`. Preserve
`versionId`, `checksum`, `sourceTimecode`, audio metadata, and provenance when available.
The result retains the complete current asset objects, including their URLs or opaque
`renderhaus-asset://` handles. It never opens, downloads, publishes, or probes media.
No remote endpoint, model, key, secret, or additional environment variable is involved.
The parser is synchronous; there is no submit/poll job.

Media matching uses embedded asset ID first, embedded version ID if no asset ID exists,
and unique filename plus whole source duration only when identity metadata is absent.
A missing explicit ID or conflicting identity blocks import instead of falling back.
Filename matching considers source basenames and the exporter's packaged media basename,
with percent-decoded paths. Duplicate filename/duration candidates are ambiguous.
Unmatched reports contain basenames, not signed media URLs. Media reference timing,
not stale `recordStartFrame` or `sourceInFrames` metadata, determines the edited windows.

`status=succeeded` returns `timeline`, a replacement Remotion assembly, plus
`unmatched_media`, `unsupported`, `warnings`, and `matched_by` counts.
`status=blocked` returns `timeline=null` and the reconciliation errors. It never returns
a partial replacement that could silently delete unmatched footage.
Malformed structure, invalid times, inconsistent frame rates, and out-of-source trims
raise validation errors. Deleting all clips is a valid empty edit.
`REMOTION_DRY_RUN=true`, the default, returns a validated `status=dry_run` preview.
A preview is not an applied import. Import itself performs no project or filesystem writes.

To apply a successful import through Deep Agents, read the existing assembly from project
files, submit the file contents and current assembly, and review the report. Retain the
previous assembly in a separate project file, save `result.timeline` to the assembly path,
and read it back. The resolve-handoff skill gives this guidance to the editor role.
Project files persist with the existing conversation checkpoint. This does not rewrite
Studio canvas nodes or the older flat `server/projects.py` timeline model. No new upload
control or timeline editor UI is included.

The returned assembly retains track order, empty tracks when represented, clip source in
and exclusive out timing, gaps, markers, static fit, and gain. OTIO track order comes from
the edited Stack; FCPXML compositing order comes from lane numbers. Nested connected
clips use their anchor's source coordinates. The exporter now includes a sequence track
table so new FCPXML exports can retain empty tracks. Older FCPXML without that table reports
that empty tracks cannot be recovered. Generated tracks retain their isolation and do not
split again on re-export. Existing asset identities and provenance remain unchanged.

Markers use `name`, `start`, and `duration` in seconds. Clip marker starts are relative to
the trimmed clip; track and document marker starts are relative to the timeline. FCPXML
marker notes and chapter type, and OTIO marker colors, are retained. These annotations do
not render on-screen. The outbound exporter does not yet serialize these imported markers.

OTIO SMPTE dissolves between a clip and a gap map to `fadeIn` or `fadeOut`, with the
required source handles included. Clip-to-clip dissolves and custom transitions block
application. FCPXML effect transitions, retimes, nested/multicam clips, J/L cuts, animated
volume, and unsupported adjustment/effect elements require baking or simplification.
The importer does not claim grade preservation. Fade and marker fields survive the returned
assembly; the existing cut-only exporter still requires baking fades before another handoff.

### Parsing and source verification

The stdlib ElementTree parser rejects entity declarations and external DOCTYPEs. The
exporter's bare `<!DOCTYPE fcpxml>` is allowed. XML depth is limited to 64 and elements to
20,000. JSON rejects duplicate keys, nonfinite numbers, depth above 64, and more than
20,000 values. OTIO decoding uses `otio.core.deserialize_json_from_string`, bypassing
adapter plugins and media retrieval. Frame times must be on the current project rate;
conform mixed-rate or subframe edits before import.

Official references read 2026-10-09:

- [Apple FCPXML reference](https://developer.apple.com/documentation/professional-video-applications/fcpxml-reference).
- [Apple FCPXML timing attributes](https://developer.apple.com/documentation/professional-video-applications/timing-attributes).
- [Apple story elements and compositing lanes](https://developer.apple.com/documentation/professional-video-applications/story-elements).
- [Apple DTD](https://developer.apple.com/documentation/professional-video-applications/document-type-definition). The public page publishes 1.10. The shared media-edit subset is accepted for 1.9–1.11; full 1.11-specific constructs and actual editor compatibility remain UNVERIFIED.
- [Apple FCPXML bundles](https://developer.apple.com/documentation/professional-video-applications/fcpxml-bundle-reference).
- [OTIO 0.18.1 serialized schema](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/v0.18.1/docs/tutorials/otio-serialized-schema.md).
- [OTIO 0.18.1 Apache-2.0 licence](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/v0.18.1/LICENSE.txt).

The project already pins `opentimelineio==0.18.1`; no dependency was added. Its permissive
code licence does not grant rights to source media. There is no new model or weights
licence, and import has `training_eligible=false`. Existing asset eligibility is preserved,
not expanded by an editor's metadata. Provider price is $0 because this is our own local
parser, not a billed Remotion render or hosted model. Cloud infrastructure charges are separate.

Run `.venv/bin/python -m unittest discover -s tests -p 'test_nle_*.py' -q` for offline
export/import tests. Fixtures include editor trim, reorder, delete, and added markers.
Tests cover fractional/drop-frame timing, ambiguous relinks, source bounds, unsupported
transitions/effects, hostile XML, dry-run flags, Lambda dispatch with offline stubs, routing,
and the Studio asset-handle boundary. These checks do not establish a real NLE or browser
round trip. Comet is unavailable in this environment, so browser E2E is blocked.

### Implementation and verification record (2026-10-09)

Offline checks passed: Ruff, 1,348 unittest cases (6 skipped), `scripts/ci_check.py`,
and the Studio TypeScript check. The offline Deep Agents graph imported the edited OTIO,
saved the replacement and backup in project files, then restored and read both in a fresh
worker. No provider or model network request was made. Browser E2E remains blocked; the
ignored report is `.renderhaus/e2e/nle-import.json`.

Changed files for this feature:

```text
.github/workflows/deploy.yml
Dockerfile.agentcore
agent/deep_agent/routing.py
agent/deep_agent/routing_policy.json
agent/deep_agent/runner.py
agent/deep_agent/skills/resolve-handoff/SKILL.md
agent/gateway_executor.py
agent/studio_agent_next.py
configs/gateway/remotion.tools.json
docs/DEEP_AGENT.md
docs/NLE_EXPORT.md
docs/SKILLS.md
docs/nle-import-decisions.tsv
docs/provider-ladder-decisions.tsv
docs/skills-drafts/resolve-handoff.md
docs/skills-drafts/resolve-roundtrip.md
providers/contracts.py
providers/nle/formats.py
providers/nle/importer.py
providers/nle/model.py
providers/registry.py
providers/remotion/api.py
scripts/ci_check.py
scripts/sync_secrets.py
server/billing_rates.py
tests/fixtures/nle_import/edited.fcpxml
tests/fixtures/nle_import/edited.otio
tests/fixtures/skill_routing.json
tests/golden/nle/timeline.fcpxml
tests/test_deep_agent.py
tests/test_nle_import.py
tests/test_provider_ladder.py
tests/test_skill_routing.py
```
