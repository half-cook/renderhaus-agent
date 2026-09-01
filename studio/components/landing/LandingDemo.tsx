"use client";

/**
 * A genuinely playable miniature of the studio canvas embedded in the
 * hero -- drag nodes, edit the prompt, place new Image/Video nodes from
 * the same bottom tool rail the real app uses, hit Generate. This never
 * calls the real (billed) provider APIs: "generating" is a client-side
 * simulation that swaps in one of a few hand-built gradient placeholders
 * keyed to the chosen preset, so anonymous landing-page traffic can't run
 * up real generation cost.
 */
import {
  Hand,
  Image as ImageIcon,
  Mic,
  MousePointer2,
  Music,
  Play,
  Type,
  Upload,
  Video,
  X,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import styles from "./LandingDemo.module.css";

type Preset = {
  id: string;
  label: string;
  prompt: string;
  gradient: string;
  ink: string;
};

const PRESETS: Preset[] = [
  {
    id: "rooftop",
    label: "Golden-hour rooftop",
    prompt: "a golden-hour rooftop, wide shot, warm light",
    gradient: "linear-gradient(165deg, #ffcf8a 0%, #ff8a5b 45%, #6b3a63 100%)",
    ink: "#2a1520",
  },
  {
    id: "rain",
    label: "Neon rain, night street",
    prompt: "neon rain on a night city street",
    gradient: "linear-gradient(165deg, #7dd3fc 0%, #6366f1 55%, #0b1023 100%)",
    ink: "#eaf6ff",
  },
  {
    id: "lake",
    label: "Mountain lake at dawn",
    prompt: "a still mountain lake at dawn",
    gradient: "linear-gradient(165deg, #bbf7d0 0%, #38bdf8 55%, #1e3a5f 100%)",
    ink: "#fef9c3",
  },
];

type Point = { x: number; y: number };
type Status = "idle" | "generating" | "done";
type GeneratorKind = "image" | "video";

type GeneratorNode = {
  id: string;
  kind: GeneratorKind;
  pos: Point;
};

const PROMPT_START: Point = { x: 6, y: 22 };
const RESULT_START: Point = { x: 46, y: 10 };
const IMAGE_TO_VIDEO_START: Point = { x: 46, y: 52 };

const RAIL_TOOLS: Array<{ id: string; label: string; icon: typeof MousePointer2; placeable?: GeneratorKind }> = [
  { id: "select", label: "Select", icon: MousePointer2 },
  { id: "hand", label: "Pan", icon: Hand },
  { id: "upload", label: "Upload", icon: Upload },
  { id: "text", label: "Text", icon: Type },
  { id: "image", label: "Image", icon: ImageIcon, placeable: "image" },
  { id: "video", label: "Video", icon: Video, placeable: "video" },
  { id: "music", label: "Music", icon: Music },
  { id: "voice", label: "Voiceover", icon: Mic },
];

const GENERATOR_LABEL: Record<GeneratorKind, string> = { image: "Image", video: "Video" };

export function LandingDemo() {
  const [presetId, setPresetId] = useState(PRESETS[0].id);
  const [prompt, setPrompt] = useState(PRESETS[0].prompt);
  const [status, setStatus] = useState<Status>("idle");
  const [resultPresetId, setResultPresetId] = useState<string | null>(null);
  const [promptPos, setPromptPos] = useState<Point>(PROMPT_START);
  const [resultPos, setResultPos] = useState<Point>(RESULT_START);
  const [videoPos, setVideoPos] = useState<Point>(IMAGE_TO_VIDEO_START);
  const [videoStatus, setVideoStatus] = useState<Status>("idle");
  const [generators, setGenerators] = useState<GeneratorNode[]>([]);
  const [activeTool, setActiveTool] = useState("select");
  const [connector, setConnector] = useState({ x1: 0, y1: 0, x2: 0, y2: 0 });
  const [videoConnector, setVideoConnector] = useState({ x1: 0, y1: 0, x2: 0, y2: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const promptNodeRef = useRef<HTMLDivElement>(null);
  const resultNodeRef = useRef<HTMLDivElement>(null);
  const videoNodeRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<number | null>(null);
  const videoTimerRef = useRef<number | null>(null);
  const placedCountRef = useRef(0);

  // Pixel-accurate, not percentage math: a node's on-screen width is a
  // fixed px value (.demo-node) while the canvas itself can be almost any
  // width, so a hardcoded "+15%" offset only lines up with the node's
  // real edge at one specific canvas width. Reading the actual rendered
  // rects instead means the line always starts/ends exactly where the
  // node border is, at any viewport size.
  useLayoutEffect(() => {
    const updateConnectors = () => {
      const canvas = canvasRef.current;
      const promptNode = promptNodeRef.current;
      const resultNode = resultNodeRef.current;
      const videoNode = videoNodeRef.current;
      if (!canvas || !promptNode || !resultNode || !videoNode) return;
      const canvasRect = canvas.getBoundingClientRect();
      const promptRect = promptNode.getBoundingClientRect();
      const resultRect = resultNode.getBoundingClientRect();
      const videoRect = videoNode.getBoundingClientRect();
      setConnector({
        x1: promptRect.right - canvasRect.left,
        y1: promptRect.top + 20 - canvasRect.top,
        x2: resultRect.left - canvasRect.left,
        y2: resultRect.top + 20 - canvasRect.top,
      });
      setVideoConnector({
        x1: resultRect.left + 24 - canvasRect.left,
        y1: resultRect.bottom - canvasRect.top,
        x2: videoRect.left + 24 - canvasRect.left,
        y2: videoRect.top - canvasRect.top,
      });
    };
    updateConnectors();
    window.addEventListener("resize", updateConnectors);
    return () => window.removeEventListener("resize", updateConnectors);
  }, [promptPos, resultPos, videoPos]);

  const resultPreset = resultPresetId ? PRESETS.find((item) => item.id === resultPresetId) : undefined;

  // A freshly generated image invalidates whatever the Image -> Video node
  // was showing -- it animated a different source image.
  useEffect(() => {
    setVideoStatus("idle");
  }, [resultPresetId]);

  const pickPreset = (next: Preset) => {
    setPresetId(next.id);
    setPrompt(next.prompt);
  };

  const generate = () => {
    if (status === "generating") return;
    if (timerRef.current) window.clearTimeout(timerRef.current);
    setStatus("generating");
    timerRef.current = window.setTimeout(() => {
      setResultPresetId(presetId);
      setStatus("done");
    }, 900);
  };

  const generateVideo = () => {
    if (!resultPreset || videoStatus === "generating") return;
    if (videoTimerRef.current) window.clearTimeout(videoTimerRef.current);
    setVideoStatus("generating");
    videoTimerRef.current = window.setTimeout(() => {
      setVideoStatus("done");
    }, 1100);
  };

  const placeGenerator = (kind: GeneratorKind) => {
    const index = placedCountRef.current;
    placedCountRef.current += 1;
    const pos: Point = {
      x: 20 + ((index * 17) % 55),
      y: 55 + ((index * 13) % 30),
    };
    setGenerators((current) => [...current, { id: `${kind}-${Date.now()}-${index}`, kind, pos }]);
  };

  const removeGenerator = (id: string) => {
    setGenerators((current) => current.filter((node) => node.id !== id));
  };

  const useTool = (tool: (typeof RAIL_TOOLS)[number]) => {
    setActiveTool(tool.id);
    if (tool.placeable) {
      placeGenerator(tool.placeable);
    }
  };

  const startDrag = (
    downEvent: React.PointerEvent<HTMLDivElement>,
    setPos: (point: Point) => void,
  ) => {
    const canvas = canvasRef.current;
    // "demo-node" is deliberately kept as a plain global class (see the
    // comment on it in globals.css) specifically so this lookup keeps
    // working -- a CSS Modules hash here would silently break every drag.
    const node = downEvent.currentTarget.closest(".demo-node");
    if (!canvas || !node) return;
    const canvasRect = canvas.getBoundingClientRect();
    const nodeRect = node.getBoundingClientRect();
    const originX = ((nodeRect.left - canvasRect.left) / canvasRect.width) * 100;
    const originY = ((nodeRect.top - canvasRect.top) / canvasRect.height) * 100;
    const nodeWidthPct = (nodeRect.width / canvasRect.width) * 100;
    const nodeHeightPct = (nodeRect.height / canvasRect.height) * 100;
    const startX = downEvent.clientX;
    const startY = downEvent.clientY;

    const onMove = (moveEvent: PointerEvent) => {
      const dxPct = ((moveEvent.clientX - startX) / canvasRect.width) * 100;
      const dyPct = ((moveEvent.clientY - startY) / canvasRect.height) * 100;
      setPos({
        x: Math.min(Math.max(originX + dxPct, 0), 100 - nodeWidthPct),
        y: Math.min(Math.max(originY + dyPct, 0), 100 - nodeHeightPct),
      });
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const startGeneratorDrag = (downEvent: React.PointerEvent<HTMLDivElement>, id: string) => {
    startDrag(downEvent, (point) =>
      setGenerators((current) => current.map((node) => (node.id === id ? { ...node, pos: point } : node))),
    );
  };

  return (
    <div className={styles["landing-demo"]}>
      <div className={styles["landing-demo-chrome"]}>
        <span className={styles["demo-chrome-dot"]} />
        <span className={styles["demo-chrome-dot"]} />
        <span className={styles["demo-chrome-dot"]} />
        <span className={styles["landing-demo-chrome-label"]}>
          Try it — drag nodes, edit the prompt, add Image/Video
        </span>
      </div>
      <div className={styles["demo-canvas"]} ref={canvasRef}>
        <svg className={styles["demo-connector"]} aria-hidden="true">
          <line x1={connector.x1} y1={connector.y1} x2={connector.x2} y2={connector.y2} />
          <line
            x1={videoConnector.x1}
            y1={videoConnector.y1}
            x2={videoConnector.x2}
            y2={videoConnector.y2}
          />
        </svg>

        <div
          ref={promptNodeRef}
          className="demo-node"
          style={{ left: `${promptPos.x}%`, top: `${promptPos.y}%` }}
        >
          <div className={styles["demo-node-header"]} onPointerDown={(event) => startDrag(event, setPromptPos)}>
            <span className={styles["demo-node-dot"]} />
            Prompt
          </div>
          <textarea
            className={styles["demo-prompt-input"]}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={4}
            aria-label="Prompt"
          />
          <div className={styles["demo-chip-row"]}>
            {PRESETS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`${styles["demo-chip"]} ${item.id === presetId ? styles.selected : ""}`}
                aria-pressed={item.id === presetId}
                onClick={() => pickPreset(item)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={styles["demo-generate-btn"]}
            onClick={generate}
            disabled={status === "generating"}
          >
            {status === "generating" ? "Generating…" : "Generate"}
          </button>
        </div>

        <div
          ref={resultNodeRef}
          className="demo-node"
          style={{ left: `${resultPos.x}%`, top: `${resultPos.y}%` }}
        >
          <div className={styles["demo-node-header"]} onPointerDown={(event) => startDrag(event, setResultPos)}>
            <span className={styles["demo-node-dot"]} />
            Result
          </div>
          <div className={styles["demo-result-frame"]}>
            {status === "generating" ? (
              <div className={styles["demo-result-loading"]}>
                <span className={styles["demo-loading-bar"]} />
              </div>
            ) : resultPreset ? (
              <div
                className={styles["demo-result-card"]}
                style={{ background: resultPreset.gradient, color: resultPreset.ink }}
              >
                <span className={styles["demo-result-caption"]}>{resultPreset.label}</span>
              </div>
            ) : (
              <p className={styles["demo-result-empty"]}>Nothing yet — hit Generate</p>
            )}
          </div>
        </div>

        <div
          ref={videoNodeRef}
          className="demo-node"
          style={{ left: `${videoPos.x}%`, top: `${videoPos.y}%` }}
        >
          <div className={styles["demo-node-header"]} onPointerDown={(event) => startDrag(event, setVideoPos)}>
            <span className={styles["demo-node-dot"]} />
            Image → Video
          </div>
          <div className={styles["demo-result-frame"]}>
            {videoStatus === "generating" ? (
              <div className={styles["demo-result-loading"]}>
                <span className={styles["demo-loading-bar"]} />
              </div>
            ) : videoStatus === "done" && resultPreset ? (
              <div className={styles["demo-video-card"]}>
                <div className={styles["demo-video-card-fill"]} style={{ background: resultPreset.gradient }} />
                <div className={styles["demo-video-play"]}>
                  <span>
                    <Play size={14} fill="currentColor" />
                  </span>
                </div>
                <span className={styles["demo-video-caption"]} style={{ color: resultPreset.ink }}>
                  {resultPreset.label} — 4s loop
                </span>
              </div>
            ) : (
              <p className={styles["demo-result-empty"]}>
                {resultPreset ? "Ready — hit Animate" : "Generate an image first"}
              </p>
            )}
          </div>
          <button
            type="button"
            className={styles["demo-generate-btn"]}
            onClick={generateVideo}
            disabled={!resultPreset || videoStatus === "generating"}
          >
            {videoStatus === "generating" ? "Animating…" : "Animate"}
          </button>
        </div>

        {generators.map((node) => {
          const Icon = node.kind === "image" ? ImageIcon : Video;
          return (
            <div
              key={node.id}
              className="demo-node"
              style={{ left: `${node.pos.x}%`, top: `${node.pos.y}%` }}
            >
              <div
                className={styles["demo-node-header"]}
                onPointerDown={(event) => startGeneratorDrag(event, node.id)}
              >
                <span className={styles["demo-node-dot"]} />
                {GENERATOR_LABEL[node.kind]}
                <button
                  type="button"
                  className={styles["demo-node-remove"]}
                  aria-label={`Remove ${GENERATOR_LABEL[node.kind]} node`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => removeGenerator(node.id)}
                >
                  <X size={11} />
                </button>
              </div>
              <div className={styles["demo-generator-body"]}>
                <Icon size={22} />
                <span>Empty {GENERATOR_LABEL[node.kind].toLowerCase()} generator</span>
              </div>
            </div>
          );
        })}

        <nav className={styles["demo-tool-rail"]} aria-label="Canvas tools">
          {RAIL_TOOLS.map((tool) => {
            const Icon = tool.icon;
            return (
              <button
                key={tool.id}
                type="button"
                className={`${styles["demo-rail-btn"]} ${activeTool === tool.id ? styles.active : ""}`}
                aria-label={tool.label}
                aria-pressed={activeTool === tool.id}
                onClick={() => useTool(tool)}
              >
                <Icon size={16} />
              </button>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
