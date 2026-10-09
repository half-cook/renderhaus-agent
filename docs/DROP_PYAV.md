# Metadata probing without PyAV

`providers/remotion/local.py::_probe` uses ffprobe when it is on PATH. Its
subprocess arguments are unchanged. Without ffprobe, it calls the original
stdlib-only parser in `providers/remotion/mp4_probe.py`.

The parser replaces the only PyAV import. PyAV is removed from project
dependencies and the Gateway Lambda pip list. No dependency, model, paid tool,
environment variable or secret is added.

## Licence rationale

PyAV 14.2.0's Python binding has a
[BSD-3-Clause licence](https://raw.githubusercontent.com/PyAV-Org/PyAV/v14.2.0/LICENSE.txt).
Its [FFmpeg build script](https://raw.githubusercontent.com/PyAV-Org/PyAV/v14.2.0/scripts/build-deps)
enables GPL, version 3 and libx264. The installed wheel contains `libx264`,
`libpostproc` and `libavcodec` under `av.libs/`. FFmpeg's
[licence reference](https://ffmpeg.org/legal.html) explains that using its GPL
parts changes the FFmpeg build's licence. These official sources were read
2026-10-09. Removing the wheel avoids shipping those libraries in the Lambda
ZIP.

The parser is original Renderhaus code. It uses Python's standard library and
copies no third-party parser code. It adds no GPL, AGPL, non-commercial weights
or other model. Existing system FFmpeg and Remotion licence obligations remain
separate from this Lambda packaging change.

## Supported metadata and limits

The fallback reads unfragmented ISO-BMFF MP4 and QuickTime MOV, including MOV
without `ftyp`. It skips media payloads and reads only box headers and required
metadata tables. It supports 64-bit box sizes, boxes extending to their parent's
end, v0/v1 `mdhd` and `mvhd`, and video/audio handler types.

The return value has `streams[]` with `codec_type`, `codec_name`,
`avg_frame_rate` and `bit_rate`, plus `format.duration` and `format.bit_rate`.
Video FPS is a reduced rational from sample count and sample timing, including
variable frame rates. Track bitrate uses `stsz` payload bytes and media duration;
format bitrate includes the whole file. Movie duration comes from `mvhd`, or
the longest usable track when the movie duration is absent.

The fallback rejects files over the existing `MAX_MEDIA_BYTES` limit of 128 MiB,
nesting deeper than 16 boxes, more than 10,000 boxes or 64 tracks, and excessive
sample-table work. Every count and read must fit its enclosing box before
iteration. It does not decode frames or verify perceptual quality.

Fragmented MP4 containing `moof` or `mvex`, and compact `stz2` sample tables, are
unsupported. WebM/MKV and other
non-ISO containers are unsupported by `_probe` without ffprobe. Recognized
WebM/MKV inputs can retain caller-supplied measured `source_fps` and optional
`source_bitrate`. Without measured FPS, assembly keeps the existing error:

```text
Download the primary video for ffprobe or supply measured source_fps; set fps only when the user requests an explicit timeline rate.
```

When the source is probed, malformed, truncated, oversized or fragmented MP4 raises
`ValueError("Local source/output is not a supported media container.")`, even
when metadata hints are supplied. As before, remote sources with both measured
FPS and bitrate skip downloading and probing. Local rendering still requires both ffmpeg
and ffprobe. Lambda rendering remains the default.

## Packaging and verification

CI validates the actual arm64 ZIP. It requires the new parser, forbids `av/`,
`av.libs/`, PyAV distribution metadata, and `libx264`/`libavcodec` shared objects
anywhere in the archive. Compressed size must stay within 50 MiB and expanded
size within Lambda's 250 MiB limit. A dependency guard test prevents `av` from
returning to `pyproject.toml`.

The previous package measured 62,745,522 bytes compressed and 155,148,362 bytes
expanded. `/workspace/rh-runs/queue-status.md` rounds the previous merge to
62.7 MB. Before uninstalling the clone's x86_64 PyAV wheel, ZIP_DEFLATED
measurement of `av/` and `av.libs/` yielded 11,289,056 and 28,332,000 compressed
bytes, respectively. Their expected saving is 39,621,056 bytes, or 39.62 MB.
This wheel-based estimate differs from the previous arm64 ZIP's measured
37,439,267 compressed bytes for those directories.

The new real arm64 ZIP was built offline from cached wheels with
`PIP_NO_INDEX=1` and `PIP_FIND_LINKS=/tmp/wan3-offline-wheels`. It measures
25,247,293 bytes compressed and 47,995,788 bytes expanded. That is a measured
37,498,229-byte compressed reduction from the previous retained ZIP. The
artifact contains no PyAV paths or `libx264`/`libavcodec` shared objects. Minor
ZIP size variation between builds comes from pip-generated metadata.

`uv lock --offline` could not regenerate the tracked lock because cached
OpenTimelineIO metadata for the project's supported Python 3.14 resolution was
unavailable. The existing lock already contains no `av` package or dependency.
It remains unchanged. A complete cached resolution or an authorized operator
lock refresh remains pending; supported Python versions were not narrowed.

With PyAV uninstalled from the clone venv and stale editable metadata removed,
the final full run passed 1,457 tests with six skips in 79.034 seconds. Ruff,
offline CI and the Studio TypeScript check also passed. The temporary Studio
`node_modules` symlink was removed. No new dry-run flag is needed.

Final check results and package measurements are recorded in
[drop-pyav-decisions.tsv](drop-pyav-decisions.tsv). The checks use synthetic boxes,
generated media, ffprobe comparisons and mocked HTTP. No live provider or AWS
calls, deployment, push or PR are authorized. Comet browser E2E is blocked
because no controllable Comet session exists in this environment. Offline
checks do not establish Studio delivery through the browser.

The parser change required no provider, tool, skill or fixture additions.
Current inventory and routing totals are in [Skill routing](SKILLS.md#offline-routing-verification).
No pricing, model licence, consent requirement or `training_eligible` decision
changes in this branch.

## Changed files

| Area | Files |
| --- | --- |
| Metadata parser and callers | `providers/remotion/mp4_probe.py`, `providers/remotion/local.py`, `providers/remotion/api.py` |
| Dependency and packaging guards | `pyproject.toml`, `scripts/deploy_gateway.py`, `scripts/ci_check.py` |
| Regression tests | `tests/test_mp4_probe.py`, `tests/test_drop_pyav_package.py`, `tests/test_remotion_quality.py` |
| Documentation and decisions | `docs/DROP_PYAV.md`, `docs/drop-pyav-decisions.tsv`, `docs/LOCAL_ASSEMBLY.md`, `docs/E2E_LIGHTHOUSE.md`, `docs/SKILLS.md`, `docs/AGENT_MODEL_SONNET55.md`, `docs/agent-model-sonnet55-decisions.tsv` |

`uv.lock`, Gateway JSON schemas, provider/routing inventories, model policies,
Studio source, secrets, `Dockerfile.agentcore` and deployment count thresholds
need no change for this private dependency removal. CI verifies the existing
schemas and inventory counts.
