# NLE track safety reference

Status: export workflow in the installed resolve-handoff skill. Local graded-timeline control remains pending.

The canonical handoff is `Remotion___export_nle_timeline`. It places generated media on new
export tracks and preserves recorded source timecodes, reel names and provenance. The exporter
cannot modify a local graded Resolve timeline or guarantee preservation through the editor's
import choices. FCPXML/OTIO re-import remains pending feat/nle-import-fcpxml.

No retired `otio_export` placeholder adds a separate operation. A completed package is an
outbound handoff, not evidence of local Resolve control or a verified round trip.
