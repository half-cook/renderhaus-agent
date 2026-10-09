# NLE re-import reference

Status: provider pending: nle import (feat/nle-import-fcpxml).

The installed exporter is outbound only. FCPXML/OTIO import needs a parser and asset
reconciliation into the Renderhaus timeline. Keep the routing fixture skipped; never
reinterpret a requested round trip as a completed outbound export.
