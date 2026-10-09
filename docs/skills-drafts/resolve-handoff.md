# Resolve handoff reference

Status: provider built. Installed as `agent/deep_agent/skills/resolve-handoff/SKILL.md`.

The live skill owns dispatch disclosure and routing. This reference retains the export contract.

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
AAF and live Resolve Studio scripting remain unimplemented. File-based FCPXML/OTIO
re-import is built through `Remotion___import_nle_timeline`; see [NLE import](../NLE_EXPORT.md#import-an-editors-timeline).
Real Resolve and browser round trips remain unverified.
