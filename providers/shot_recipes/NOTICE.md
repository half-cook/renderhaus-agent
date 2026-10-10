# Shot recipe card import notice

Origin: https://github.com/Vincentwei1021/video-shotcraft

Source commit: 5ddbf521038b0a7accfb6dc1e0a9eb29c67277ab (short id 5ddbf52).

Licence: Apache-2.0. The accompanying LICENSE is copied from the source repository.
The source repository has no NOTICE file; this notice is authored by Renderhaus.

The 157 Markdown cards under cards/ were imported unmodified, preserving their
original Chinese prose and frontmatter. ATTRIBUTION.md is the source repository's
unmodified provenance statement. No source code, reference implementations,
previews, screenshots, textures, audio or other media are included.

Renderhaus-authored additions are separate: index.json contains derivative English
summaries, search aliases, typical duration metadata, motion hints and cue names;
BRAND_SCAN.json records the source-text hygiene review. Numeric durations are
planning defaults authored from the cards. For cards whose timing depends on a
host shot, the index records a typical example duration rather than changing the
source text. These additions are not upstream-authored text.

The source ATTRIBUTION.md says that techniques were reimplemented from scratch,
but that reference works were not licensed to the source authors. Apache-2.0
covers the imported card data; it does not grant rights in third-party reference
works, distinctive expression, product identities or assets. Reference product
names remain only in the verbatim cards and provenance records. English metadata
uses neutral descriptions. Paths in the cards' reference-implementation sections
are inert provenance text: the referenced implementations are not shipped and the
paths do not resolve in this import.

One public id is neutralized: index id ground-skim maps to the unmodified source
card ui-entrance/runway-ground-skim.md. The source filename and frontmatter name
are preserved for integrity, and the public id avoids a provider-name collision.

All frontmatter fields are single-line scalar entries. In 24 original cards,
a quoted opening phrase continues with unquoted prose on the same line, so
strict YAML parsers reject that source formatting. Preserve the card bytes and
read the bounded key/scalar lines rather than rewriting upstream text. The
provenance scan records these 24 paths.

SFX cues are category names only. No source audio was copied, downloaded or
referenced by local file. SFX assets need Mixkit terms review before use; until a
human completes that review, actual effects must come from a user-supplied asset
library or the SFX stem remains empty with a disclosed note. No motion preview
media are included.
