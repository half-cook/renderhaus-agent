# Internal provenance

Origin is [lemomo-ai/lemo-opuscar](https://github.com/lemomo-ai/lemo-opuscar)
at commit `e3cb16f63768c68693ff0e15171d6e755457cc32`, read 2026-10-10.
Copyright (c) 2026 LemoLab. The [MIT licence](LICENSE) is kept unmodified.
The public [styleboard](https://lemomo-ai.github.io/lemo-opuscar/opuscar98/)
describes the 98-film set.

`source.json` preserves the original UTF-8 text of 130 files, unmodified.
These are `styleboard/opuscar98_styles.json` and `style.json`, `STYLE.md`, and
`DEMO.md` in each of 43 style directories. `_template` is excluded.
The JSON wrapper stores each original file as a string and records its SHA-256.
Decode that string to recover the original bytes. No source tools, code files,
posters, frames, music, voice, subtitles, fonts, or demo media are imported.
The demos' third-party assets retain their own licences and are excluded.

`normalization.json` and `scan_terms.json` are Renderhaus-authored derivative
metadata. `BRAND_SCAN.json` records the deny-list, every prompt and direction
adaptation, before and after text, source mapping, and unresolved matches.
The generated skill index contains descriptive labels, scrubbed style prompts,
camera notes, uses, keywords, and aliases. The 98 specialized treatments and
43 general guides remain distinct. Shared medium families are not identical
prompts and do not justify dropping a source record.

All files in this directory are internal provenance. Film titles, artist
names, characters, brands, and reference works belong here only. The runtime
loads the safe derivative index and never loads this directory. The skill
filesystem does not mount it. Do not echo source text, mappings, scan terms,
or notices into user responses, storyboards, or media prompts.

Mapping a named real film's look onto a user's topic can imply association or
create intellectual-property risk. MIT permission to adapt text does not grant
film, character, trademark, likeness, soundtrack, or media rights. Prompts
describe materials, palette, lighting, composition, and movement only.
No model or model-training licence is added. Existing training eligibility
decisions and paid-media approval rules remain unchanged.

Rebuild with `.venv/bin/python scripts/import_art_style_catalog.py`.
Check reproducibility with the same command plus `--check`.
