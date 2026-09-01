"use client";

import { Binary, Copy, Download, RefreshCcw, Upload, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useCanvasStore } from "@/lib/canvas/store";

// Classic light-to-dense ramp -- ten levels from "nothing" to "solid ink",
// the same shape used across countless terminal/ASCII-art tools since the
// 90s. Ours specifically, tuned for light characters on a dark canvas: a
// bright source pixel should map to the densest glyph (most visible ink
// against --bg), a dark pixel to the sparse end (blends into --bg).
const DEFAULT_CHARSET = " .:-=+*#%@";
// A monospace glyph cell is taller than it is wide -- without this
// correction the render comes out squashed vertically.
const FONT_ASPECT = 0.55;
const OUTPUT_WIDTH = 820;
const MIN_COLUMNS = 40;
const MAX_COLUMNS = 220;

type Quality = "low" | "mid" | "high";
const QUALITY_COLUMNS: Record<Quality, number> = { low: 60, mid: 100, high: 160 };
type MediaKind = "image" | "video";

function luminance(r: number, g: number, b: number): number {
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

export function AsciiPanel() {
  const open = useCanvasStore((state) => state.asciiPanelOpen);
  const setOpen = useCanvasStore((state) => state.setAsciiPanelOpen);
  const setActiveTool = useCanvasStore((state) => state.setActiveTool);

  const [file, setFile] = useState<File | null>(null);
  const [mediaKind, setMediaKind] = useState<MediaKind | null>(null);
  const [quality, setQuality] = useState<Quality>("mid");
  const [columns, setColumns] = useState(QUALITY_COLUMNS.mid);
  const [threshold, setThreshold] = useState(0);
  const [charset, setCharset] = useState(DEFAULT_CHARSET);
  const [inverted, setInverted] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [ready, setReady] = useState(false);
  const [grid, setGrid] = useState<{ cols: number; rows: number } | null>(null);
  const [copyLabel, setCopyLabel] = useState("Copy as text");

  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const sampleCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const outputCanvasRef = useRef<HTMLCanvasElement>(null);
  const objectUrlRef = useRef<string | null>(null);
  const gridCharsRef = useRef<{ chars: string[]; cols: number; rows: number } | null>(null);

  const render = useCallback(() => {
    const output = outputCanvasRef.current;
    let sample = sampleCanvasRef.current;
    if (!sample) {
      sample = document.createElement("canvas");
      sampleCanvasRef.current = sample;
    }
    const source: HTMLImageElement | HTMLVideoElement | null =
      mediaKind === "image" ? imageRef.current : mediaKind === "video" ? videoRef.current : null;
    if (!output || !source) return;
    const sw = mediaKind === "video" ? (source as HTMLVideoElement).videoWidth : (source as HTMLImageElement).naturalWidth;
    const sh = mediaKind === "video" ? (source as HTMLVideoElement).videoHeight : (source as HTMLImageElement).naturalHeight;
    if (!sw || !sh) return;

    const cols = Math.max(MIN_COLUMNS, Math.min(MAX_COLUMNS, columns));
    const rows = Math.max(1, Math.round(cols * (sh / sw) * FONT_ASPECT));

    sample.width = cols;
    sample.height = rows;
    const sctx = sample.getContext("2d", { willReadFrequently: true });
    if (!sctx) return;
    sctx.drawImage(source, 0, 0, cols, rows);
    const { data } = sctx.getImageData(0, 0, cols, rows);

    const ramp = [...(charset || DEFAULT_CHARSET)];
    if (inverted) ramp.reverse();
    const rampMax = Math.max(1, ramp.length - 1);
    const bias = threshold * 2.55;
    const chars: string[] = new Array(cols * rows);
    for (let i = 0; i < cols * rows; i += 1) {
      const o = i * 4;
      const l = luminance(data[o], data[o + 1], data[o + 2]);
      const alpha = data[o + 3] / 255;
      const adjusted = Math.min(255, Math.max(0, l * alpha + bias));
      chars[i] = ramp[Math.round((adjusted / 255) * rampMax)];
    }
    gridCharsRef.current = { chars, cols, rows };
    setGrid({ cols, rows });

    const cellWidth = OUTPUT_WIDTH / cols;
    const cellHeight = cellWidth / FONT_ASPECT;
    const rootStyle = getComputedStyle(document.documentElement);
    const charColor = rootStyle.getPropertyValue("--color-port-image").trim() || "#818cf8";
    const bgColor = rootStyle.getPropertyValue("--bg").trim() || "#0a0a0a";

    output.width = OUTPUT_WIDTH;
    output.height = Math.round(rows * cellHeight);
    const octx = output.getContext("2d");
    if (!octx) return;
    octx.fillStyle = bgColor;
    octx.fillRect(0, 0, output.width, output.height);
    octx.font = `${Math.ceil(cellHeight)}px "Geist Mono", ui-monospace, monospace`;
    octx.textBaseline = "top";
    octx.fillStyle = charColor;
    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const ch = chars[row * cols + col];
        if (ch === " ") continue;
        octx.fillText(ch, col * cellWidth, row * cellHeight);
      }
    }
  }, [charset, columns, inverted, mediaKind, threshold]);

  const renderRef = useRef(render);
  useEffect(() => {
    renderRef.current = render;
    if (ready) render();
  }, [render, ready]);

  const resetControls = () => {
    setQuality("mid");
    setColumns(QUALITY_COLUMNS.mid);
    setThreshold(0);
    setCharset(DEFAULT_CHARSET);
    setInverted(false);
  };

  const loadFile = useCallback((next: File) => {
    const kind: MediaKind | null = next.type.startsWith("video/")
      ? "video"
      : next.type.startsWith("image/")
        ? "image"
        : null;
    if (!kind) return;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const url = URL.createObjectURL(next);
    objectUrlRef.current = url;
    setFile(next);
    setMediaKind(kind);
    setReady(false);
    setGrid(null);
    setDuration(0);
    setCurrentTime(0);

    if (kind === "image") {
      videoRef.current = null;
      const img = new Image();
      img.onload = () => {
        imageRef.current = img;
        setReady(true);
      };
      img.src = url;
    } else {
      imageRef.current = null;
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      video.preload = "auto";
      video.addEventListener("loadeddata", () => {
        setDuration(video.duration || 0);
        setReady(true);
      });
      video.addEventListener("seeked", () => {
        setCurrentTime(video.currentTime);
        renderRef.current();
      });
      video.src = url;
      videoRef.current = video;
    }
  }, []);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (open && event.key === "Escape") {
        setOpen(false);
        setActiveTool("select");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setActiveTool, setOpen]);

  if (!open) {
    return null;
  }

  const close = () => {
    setOpen(false);
    setActiveTool("select");
  };

  const downloadPng = () => {
    const canvas = outputCanvasRef.current;
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = "renderhaus-ascii.png";
    a.click();
  };

  const copyText = async () => {
    const current = gridCharsRef.current;
    if (!current) return;
    const lines: string[] = [];
    for (let row = 0; row < current.rows; row += 1) {
      lines.push(current.chars.slice(row * current.cols, (row + 1) * current.cols).join(""));
    }
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyLabel("Copied!");
    } catch {
      setCopyLabel("Couldn't copy");
    } finally {
      setTimeout(() => setCopyLabel("Copy as text"), 1500);
    }
  };

  return (
    <div
      className="ascii-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="ASCII converter"
      onClick={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="ascii-modal">
        <div className="ascii-modal-header">
          <span className="ascii-modal-title">
            <Binary size={16} />
            ASCII converter
          </span>
          <button type="button" className="icon-btn" aria-label="Close" onClick={close}>
            <X size={16} />
          </button>
        </div>
        <div className="ascii-modal-body">
          <div className="ascii-controls">
            <div
              className={dragOver ? "ascii-dropzone drag" : "ascii-dropzone"}
              role="button"
              tabIndex={0}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") fileInputRef.current?.click();
              }}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragOver(false);
                const dropped = event.dataTransfer.files?.[0];
                if (dropped) loadFile(dropped);
              }}
            >
              <Upload size={18} />
              <span>{file ? "Replace file" : "Drag and drop, or click to upload"}</span>
            </div>
            {file ? (
              <p className="ascii-file-meta">
                {file.name} · {(file.size / (1024 * 1024)).toFixed(1)} MB
              </p>
            ) : null}
            <input
              ref={fileInputRef}
              type="file"
              hidden
              accept="image/*,video/*"
              onChange={(event) => {
                const picked = event.target.files?.[0];
                event.target.value = "";
                if (picked) loadFile(picked);
              }}
            />

            <label className="field">
              <span>Quality</span>
              <select
                value={quality}
                onChange={(event) => {
                  const next = event.target.value as Quality;
                  setQuality(next);
                  setColumns(QUALITY_COLUMNS[next]);
                }}
              >
                <option value="low">Low (fast)</option>
                <option value="mid">Mid (balanced)</option>
                <option value="high">High (detailed)</option>
              </select>
            </label>
            <label className="field">
              <span>Columns · {columns}</span>
              <input
                type="range"
                min={MIN_COLUMNS}
                max={MAX_COLUMNS}
                value={columns}
                onChange={(event) => setColumns(Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>Threshold · {threshold}</span>
              <input
                type="range"
                min={-100}
                max={100}
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>Charset</span>
              <input
                type="text"
                value={charset}
                onChange={(event) => setCharset(event.target.value)}
              />
            </label>
            <div className="ascii-actions-row">
              <button
                type="button"
                className={inverted ? "field-pill selected" : "field-pill"}
                onClick={() => setInverted((value) => !value)}
              >
                Invert
              </button>
              <button type="button" className="field-pill" onClick={resetControls}>
                <RefreshCcw size={13} /> Reset
              </button>
            </div>
          </div>

          <div className="ascii-preview">
            <div className="ascii-preview-meta">
              <span>Preview</span>
              {grid ? (
                <span className="ascii-preview-dims">
                  {grid.cols}x{grid.rows}
                </span>
              ) : null}
            </div>
            <div className="ascii-canvas-wrap">
              {ready ? (
                <canvas ref={outputCanvasRef} />
              ) : (
                <p className="inspector-note">Upload an image or video to see it rendered in ASCII.</p>
              )}
            </div>
            {mediaKind === "video" && duration > 0 ? (
              <div className="ascii-scrubber">
                <input
                  type="range"
                  min={0}
                  max={duration}
                  step={0.01}
                  value={currentTime}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    setCurrentTime(next);
                    if (videoRef.current) videoRef.current.currentTime = next;
                  }}
                />
                <span>
                  {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
                </span>
              </div>
            ) : null}
            <div className="ascii-export-row">
              <button type="button" className="field-pill" disabled={!ready} onClick={downloadPng}>
                <Download size={13} /> Download PNG
              </button>
              <button type="button" className="field-pill" disabled={!ready} onClick={() => void copyText()}>
                <Copy size={13} /> {copyLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
