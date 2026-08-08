import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { COMPOSITION_HEIGHT, COMPOSITION_WIDTH } from "@/components/editor/remotion/constants";

// Local-dev stand-in for the managed proxy-transcode job planned in
// design/ARCHITECTURE.md §10.2/§10.3. Shells out to the ffmpeg on this machine; a
// real deploy replaces this route's body with a job enqueue against managed
// workers, not a redesign of the client contract (upload -> proxy URL).
const PROXY_DIR = path.join(process.cwd(), "public", "proxies");

// Hardening below responds directly to real ffmpeg-as-a-service incidents
// (untrusted input is a code-execution surface via decoder bugs, not just a
// shell-escaping problem — see design/ARCHITECTURE.md §10.3) rather than
// hypothetical ones.
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024; // 2 GiB — tune once real usage data exists
const FFMPEG_TIMEOUT_MS = 5 * 60 * 1000; // kill runaway/hung encodes rather than block the worker forever
const ALLOWED_EXTENSIONS = new Set([".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"]);

function runFfmpeg(args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    // argv array, never a shell string — spawn (not exec) means there is no
    // shell to inject into, regardless of what's in the filename or args.
    const proc = spawn("ffmpeg", args);
    let stderr = "";
    const timeout = setTimeout(() => {
      proc.kill("SIGKILL");
      reject(new Error(`ffmpeg exceeded ${FFMPEG_TIMEOUT_MS}ms and was killed`));
    }, FFMPEG_TIMEOUT_MS);

    proc.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });
    proc.on("error", (err) => {
      clearTimeout(timeout);
      reject(new Error(`Could not run ffmpeg (${err.message}) — is it installed and on PATH?`));
    });
    proc.on("close", (code) => {
      clearTimeout(timeout);
      if (code === 0) resolve();
      else reject(new Error(`ffmpeg exited with code ${code}: ${stderr.slice(-2000)}`));
    });
  });
}

export async function POST(request: Request): Promise<Response> {
  const formData = await request.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return Response.json({ error: "Expected a 'file' field in form data" }, { status: 400 });
  }

  // Reject oversized/wrong-type uploads before ever touching disk or ffmpeg
  // — never trust file.type alone (client-controlled), but it's a cheap
  // first filter alongside the extension allowlist.
  if (file.size > MAX_UPLOAD_BYTES) {
    return Response.json({ error: `File exceeds the ${MAX_UPLOAD_BYTES} byte limit` }, { status: 413 });
  }
  const inputExt = path.extname(file.name).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(inputExt) || !file.type.startsWith("video/")) {
    return Response.json({ error: `Unsupported file type: ${file.name}` }, { status: 415 });
  }

  await mkdir(PROXY_DIR, { recursive: true });

  const jobId = randomUUID();
  const inputPath = path.join(tmpdir(), `renderhaus-transcode-${jobId}${inputExt}`);
  const outputName = `${jobId}.mp4`;
  const outputPath = path.join(PROXY_DIR, outputName);

  await writeFile(inputPath, Buffer.from(await file.arrayBuffer()));

  try {
    await runFfmpeg([
      "-y",
      // Refuses to follow any protocol the demuxer might discover inside the
      // file itself (e.g. a crafted playlist/concat reference) — the input
      // is a local temp file we just wrote, nothing else should be reachable.
      "-protocol_whitelist",
      "file,pipe",
      "-i",
      inputPath,
      "-vf",
      `scale='min(iw,${COMPOSITION_WIDTH})':'min(ih,${COMPOSITION_HEIGHT})':force_original_aspect_ratio=decrease:force_divisible_by=2`,
      "-c:v",
      "libx264",
      "-preset",
      "veryfast",
      "-crf",
      "23",
      "-pix_fmt",
      "yuv420p",
      "-c:a",
      "aac",
      "-b:a",
      "128k",
      "-movflags",
      "+faststart",
      outputPath,
    ]);
  } finally {
    await rm(inputPath, { force: true });
  }

  return Response.json({ url: `/proxies/${outputName}` });
}
