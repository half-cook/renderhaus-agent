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
the handoff onto new tracks. Resolve-to-Renderhaus re-import is future work only.

The design was informed by FilmCraft's interchange implementation at
`/workspace/filmcraft/crates/interchange`, especially its EDL, FCP7 XML, FCPXML, and OTIO modules.
No reference source code was copied verbatim.
