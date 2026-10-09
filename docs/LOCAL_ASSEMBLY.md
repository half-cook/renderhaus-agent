# Local assembly and Gateway

Production still defaults to Remotion Lambda. For development without AWS, set
`REMOTION_RENDER_BACKEND=local` and `REMOTION_DRY_RUN=false`. Both `ffmpeg` and
`ffprobe` must be installed. No provider generation is enabled by this setting.

`Remotion___render_timeline` uses the existing typed arguments. Each visual or
`audio_tracks` entry accepts exactly one `url` or `output_path`. A provider's
local `output_path` needs no `file://` prefix and must resolve inside the
configured `RENDERHAUS_MEDIA_DIR` or the workspace `.renderhaus` directory.
Lambda can upload the same local sources using its existing S3 preparation.

Omit `fps` unless the customer requests a timeline frame rate. The primary video
supplies its measured frame rate, including fractional rates such as 30000/1001;
image-only timelines default to 30 fps. Sources are inspected with ffprobe when
available and the stdlib-only ISO-BMFF parser otherwise, including Python Gateway
Lambda. The fallback supports unfragmented MP4/MOV, including video and audio
tracks. WebM/MKV requires ffprobe or caller-supplied measured `source_fps`;
measured `source_bitrate` is optional. Fragmented MP4 is unsupported by the
fallback. [DROP_PYAV.md](DROP_PYAV.md) records the parser limits.
Trusted HTTPS video is measured automatically before submitting a render:
`fal.media` and its subdomains, configured S3 bucket hosts, and existing
`REMOTION_LOCAL_MEDIA_HOSTS` overrides. Downloads reject redirects/private DNS,
cap each source at 128 MiB and use a 30-second measurement deadline.
Prior measured `visuals[].source_fps` and `visuals[].source_bitrate` can avoid the
download. Unavailable source metadata blocks submission rather than guessing fps.

`video_bitrate` is an optional positive integer target in bits per second. Both
backends use at least 1.25 times the highest measured source-video bitrate to
allow for assembly overhead. With ffprobe, containers such as Matroska may omit stream
bitrate; the measured container bitrate supplies a conservative fallback.
Without a measured bitrate or explicit target,
they use CRF18. Lambda receives the same frame rate and quality settings, with
JPEG quality 100 for intermediate frames. The generated 30 fps regression
fixture exports at 30/1 and 593,506 b/s from a 566,061 b/s source. These offline
checks verify that fixture; they do not measure perceptual quality for every codec.
The pure conversational-edit preview uses 30 fps for its preview document when
unset, records that distinction in `qc_expectations`, and omits fps from final
`render_arguments` so the renderer measures the source.

The local backend submits ffmpeg asynchronously. Poll
`Remotion___get_render_progress` with its returned `render_id` and `bucket_name=local`
sentinel. A separate local worker waits for ffmpeg and atomically persists its terminal
exit code, surviving Gateway restarts. Success requires exit code zero and a
nonempty MP4 with a video stream and the expected ffprobe duration. A partial
file or progress=end message never establishes success. The result contains `output_path`, `filename`,
`size_bytes`, and `backend=local`; the Studio can ingest the local artifact.
Jobs and artifacts live under `RENDERHAUS_MEDIA_DIR/remotion/local/`.

The backend renders the shared timeline document: source trims, playback speed,
ordered visual layers and start times, cover/contain fitting, crop positions,
opacity and fades; source-video audio and independent audio tracks with source
trims, start, duration, volume and fades. Audio never extends the visual length.
Titles/subtitles, motion presets, grading, scaling and rotation require Lambda
and fail explicitly in local mode. This is a development assembly backend, not
a replacement for the full Remotion renderer.

Local render downloads require HTTPS on exact hosts listed in the comma-separated
`REMOTION_LOCAL_MEDIA_HOSTS` setting. The list defaults empty. Private-address
hosts, redirects, credentials in URLs, `file://`, and sources outside local
media roots are refused. Assets are downloaded with bounded requests and byte
limits before ffmpeg receives local paths. Renders are limited to 600 seconds
and 60 assets, 128 MiB per source and 384 MiB total. The existing
`REMOTION_RENDER_TIMEOUT_SECONDS` defaults to 1200 for local jobs too.

Start a loopback MCP Gateway with progressive tool discovery:

```bash
AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP=true \
  .venv/bin/python scripts/local_gateway.py --port 8765 \
  --ledger .renderhaus/e2e/local-gateway.jsonl
```

Configure `AGENTCORE_GATEWAY_URL=http://127.0.0.1:8765/mcp` and
`AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP=true` in the local agent process.
`tools/list` exposes only `x_amz_bedrock_agentcore_search(query, limit=8)`.
Search returns at most 20 matching committed schemas with real `Target___tool`
names. Calls dispatch through `providers.registry.dispatch`, enforcing the
same contracts as the Lambda handler. Provider dry-run defaults remain intact.

An optional `--max-spend-cents N` enables a conservative cap using the existing
billing estimator; unknown estimates block. In-flight calls reserve their
estimate. Provider exceptions remain charged against the cap because an
accepted paid request can fail during delivery. Dry runs release the reserve.
The optional ledger persists charges across Gateway restarts and records only
tool names, statuses, cost and latency, without arguments, credentials or URLs.
Use a separate ledger for each run; the local development cap assumes one
Gateway writer. Host approval and autonomous spending rules remain in the agent.

Offline regression checks render synthetic clips and audio, poll the actual
MP4, inspect duration/streams, and decode frames/audio to verify trims, fitting
and delayed voiceover. They support the application check; browser E2E and the
operator's live lighthouse rerun are still required. Comet is unavailable in
this workspace, so browser validation remains blocked.

No new model, training policy, secret or paid endpoint is introduced.
Local rendering uses a system ffmpeg binary. Metadata probing uses ffprobe or
original Renderhaus code using the Python standard library. The Gateway Lambda
package contains no PyAV package or bundled FFmpeg libraries.
Renderhaus's existing Remotion licence obligations remain.

Both deployment entrypoints use a content-hashed S3 ZIP when the package exceeds
Lambda's 50 MiB direct-upload
limit, and check that the existing `AWS_S3_BUCKET` or `REMOTION_APP_BUCKET_NAME`
is in the function's region. CI checks the remaining arm64 modules, a 50 MiB
compressed limit, the 250 MiB expanded limit and the absence of PyAV and
FFmpeg shared libraries. [DROP_PYAV.md](DROP_PYAV.md) records package measurements.
No deployment was performed here.

Official references read 2026-10-09: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html),
[FFmpeg encoding options](https://ffmpeg.org/ffmpeg-codecs.html),
[Remotion Lambda render options](https://www.remotion.dev/docs/lambda/rendermediaonlambda),
[FFmpeg licence](https://ffmpeg.org/legal.html), and
[Remotion licence](https://www.remotion.dev/docs/license).
Additional sources read 2026-10-09:
[Lambda limits](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html),
[S3 function-code contract](https://docs.aws.amazon.com/lambda/latest/api/API_UpdateFunctionCode.html),
and [Lambda Python runtimes](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html).
