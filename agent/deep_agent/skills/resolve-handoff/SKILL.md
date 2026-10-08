---
name: resolve-handoff
description: Export existing Renderhaus media as OTIO, FCPXML, EDL, and a media ZIP for an editor or DaVinci Resolve.
metadata:
  include_tools: call_editor_tool
  gateway_tools: Remotion___export_nle_timeline
---

# Resolve handoff

Search Gateway for `Remotion___export_nle_timeline` and read its input schema.
The seed aliases `otio_export`, `fcpxml_export`, `edl_export`, and `media_package` all map
to this one tool through `call_editor_tool`. One invocation creates the complete handoff.
Do not submit a separate export for each format. The contract is documented in
`docs/NLE_EXPORT.md`; it is a file-based export and requires no Resolve remote connection.

Use the existing Remotion assembly and its pinned asset versions. Pass its frozen snapshot
as JSON-encoded `timeline_json`, with `document` and `renderConfig`. Keep immutable
`versionId` separate from the media URL. Retain each source's SHA-256 checksum,
`sourceTimecode`, `reelName`, complete `durationSec`, nonempty `provenance`, and `generated`
boolean. Video assets also need explicit `hasAudio`. If source metadata is missing, request
it before export. Do not fabricate timecode, provenance, an edit, or a transcript.

The exporter preserves cuts and gaps. Bake unsupported titles, effects, fades, or retimes
before the snapshot. Generated assets occupy new export tracks. Existing picture tracks
remain separate. That separation does not guarantee grade preservation in every NLE import.

Return the completed ZIP artifact path or download link from the successful tool result.
The ZIP contains OTIO, FCPXML, per-track CMX3600 EDLs, a manifest, and referenced media.
Check that the actual artifact opens before claiming a usable handoff. A dry-run or failed
export is incomplete. Explain its reported error and retain the original snapshot.

Tell the editor to extract the complete ZIP with its folder structure intact, then import
a new timeline. FCPXML is the Resolve-oriented second export; importing it does not require
the cloud agent to control Resolve. Transfer generated clips onto new destination tracks
when finishing a graded timeline. Premiere compatibility and real Resolve round trips
remain unverified. AAF is unimplemented and untested.

Live Resolve control, transcript rough cuts, automatic silence cuts, automatic subtitles,
Resolve-to-Renderhaus re-import, and modifications inside an existing graded timeline are
pending integration drafts. Local scripting generally needs Resolve Studio on the editor's
machine. The built export tool does not establish those capabilities.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
