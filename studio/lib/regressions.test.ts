import assert from "node:assert/strict";
import test from "node:test";

import { streamAgentPrompt } from "./api";
import { runCreativeNode } from "./canvas/graph-execution";
import type { CanvasNode } from "./canvas/connection-validation";

function videoNode(): CanvasNode {
  return {
    id: "video-1",
    type: "video",
    position: { x: 0, y: 0 },
    data: {
      kind: "video",
      title: "Launch clip",
      toolId: "video.generate",
      providerId: "seedance",
      toolName: "text_to_video",
      config: { prompt: "A polished product launch" },
      status: "idle",
    },
  } as CanvasNode;
}

for (const providerStatus of ["expired", "timed_out"]) {
  test(`runCreativeNode treats ${providerStatus} without a job ID as failed`, async () => {
    const node = videoNode();
    const patch = await runCreativeNode(node, [node], [], "project-1", async () => ({
      result: { status: providerStatus },
      assets: [],
    }));

    assert.equal(patch.status, "failed");
    assert.equal(patch.error, "Generation failed.");
    assert.equal(patch.jobId, undefined);
  });
}

test("streamAgentPrompt resumes polling when SSE ends before a terminal event", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const requests: string[] = [];

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      setTimeout(callback: () => void) {
        callback();
        return 0;
      },
    },
  });
  globalThis.fetch = async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.endsWith("/api/studio/agent/stream")) {
      return new Response(
        'data: {"type":"RUN_STARTED","threadId":"project-1","runId":"job-1"}\n\n',
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      );
    }
    return new Response(
      JSON.stringify({
        job_id: "job-1",
        status: "completed",
        message: "Recovered through polling.",
        result: {
          title: "Recovered result",
          summary: "Complete.",
          markdown: "# Recovered result",
          filename: "recovered.md",
          tool_events: [],
          assets: [],
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await streamAgentPrompt("Make a result", "project-1", [], []);
    assert.equal(result.status, "completed");
    assert.equal(result.result.title, "Recovered result");
    assert.deepEqual(requests, [
      "/api/studio/agent/stream",
      "/api/studio/agent/job-1",
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) {
      Object.defineProperty(globalThis, "window", originalWindow);
    } else {
      Reflect.deleteProperty(globalThis, "window");
    }
  }
});
