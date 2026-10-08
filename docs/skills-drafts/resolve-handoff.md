---
name: resolve-handoff
description: Export a Renderhaus assembly for an editor when the user says "send to Resolve", "give my editor a timeline", or "export XML/EDL".
metadata:
  include_tools:
    - export_nle_timeline
---

# Resolve handoff

Use `export_nle_timeline`, exposed as `Remotion___export_nle_timeline` on Gateway, for an
export-first editor handoff. Read [NLE export](../NLE_EXPORT.md) for the snapshot contract.

Use the existing Remotion assembly and its pinned asset versions. Retain each source's
timecode, reel name, checksum, and provenance. If the assembly or required source metadata
is missing, request that information before export. Do not invent an edit or source timecode.

Pass the assembly snapshot as `timeline_json`. Keep immutable `versionId` separate from the
media URL. Mark generated assets explicitly so the exporter places them on new tracks.

Return the completed zip download link or local artifact path from the tool result.
The zip contains OTIO, FCPXML, per-track CMX3600 EDLs, a manifest, and referenced media.
A dry-run response or failed export is incomplete. Explain the reported error.

Tell the editor to extract the zip with its folder structure intact, then import a new
timeline. When bringing generated clips into a graded timeline, use new destination tracks.
FCPXML is the Resolve-oriented second export. Premiere compatibility remains unverified.

Do not claim that this tool opens Resolve or protects grades through every import choice.
AAF is unimplemented and untested, pending a real Resolve round trip. A local bridge using
Resolve Studio scripting on the editor's machine and Resolve-to-Renderhaus re-import are
future work only.
