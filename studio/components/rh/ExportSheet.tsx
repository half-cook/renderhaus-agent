"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Download, FileJson, X } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { Dialog, DialogClose, DialogDescription, DialogOverlay, DialogPortal, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { studioFetch } from "@/lib/authenticated-fetch";
import { useCanvasStore } from "@/lib/canvas/store";
import { exportModel, type ExportModel } from "@/lib/rh/export";
import { safeCopy } from "@/lib/rh/billing";
import { formatCents } from "@/lib/rh/money";
import { CapRow, Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

export function ExportSheet() {
  const projectId = useCanvasStore((state) => state.projectId);
  const projectName = useCanvasStore((state) => state.projectName);
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState<ExportModel | null>(null);
  const [projectFile, setProjectFile] = useState<{ url: string; bytes: number } | null>(null);
  const [error, setError] = useState(false);
  const blobRef = useRef<string | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setModel(null); setError(false); setProjectFile(null);
    if (blobRef.current) { URL.revokeObjectURL(blobRef.current); blobRef.current = null; }
    void studioFetch(`/api/studio/projects/${encodeURIComponent(projectId)}/export`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Export unavailable");
      const payload: unknown = await response.json();
      if (!cancelled) setModel(exportModel(payload));
    }).catch(() => { if (!cancelled) { setError(true); setModel(exportModel(null)); } });
    return () => { cancelled = true; };
  }, [open, projectId]);
  useEffect(() => () => { if (blobRef.current) URL.revokeObjectURL(blobRef.current); }, []);
  const prepareProject = () => {
    const state = useCanvasStore.getState();
    const blob = new Blob([JSON.stringify({ schemaVersion: 2, projectName: state.projectName, nodes: state.nodes, edges: state.edges, viewport: state.viewport }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob); blobRef.current = url;
    setProjectFile({ url, bytes: blob.size });
  };
  const done = projectFile != null || model?.state === "done";
  const download = projectFile?.url ?? (model?.state === "done" ? model.downloadPath : undefined);
  const filename = `${safeCopy(projectName, "project").replace(/[^a-z0-9-]+/gi, "-").toLowerCase() || "project"}.${projectFile || model?.format === "project_json" ? "json" : model?.format ?? "json"}`;
  const bytes = projectFile?.bytes ?? model?.sizeBytes;
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><button className="text-btn" type="button">Export</button></DialogTrigger>
    <DialogPortal><DialogOverlay className="rh-export-overlay" /><DialogPrimitive.Content className="rh-export-sheet" data-shot={done ? "export-done-ready" : model ? "export-ready" : undefined} onOpenAutoFocus={(event) => { event.preventDefault(); titleRef.current?.focus(); }}>
      <header><p className="rh-eyebrow">{safeCopy(projectName, "Project")}</p><DialogTitle asChild><h2 className="rh-h1" tabIndex={-1} ref={titleRef}>{done ? "Your file is ready." : "Export your project."}</h2></DialogTitle><DialogDescription>{done ? "Download the file below." : "Review the format and delivery details before exporting."}</DialogDescription><DialogClose asChild><button type="button" className="rh-btn rh-btn-quiet rh-export-close" aria-label="Close export"><X size={18} /></button></DialogClose></header>
      <div className="rh-export-body">
        {!model ? <p role="status" className="rh-fg3">Loading export details…</p> : <>
          {done ? <div className="rh-export-done"><Check size={24} aria-hidden="true" /><h3 className="rh-h3">{projectFile ? "Editable project JSON" : "Export complete"}</h3><p className="rh-fg2">{projectFile ? "Contains your canvas, connections and timeline trims." : "The server’s completed file is ready to download."}</p></div> : null}
          <dl className="rh-export-details"><div><dt>Format</dt><dd>{projectFile || model.format === "project_json" ? "Project JSON" : model.format.toUpperCase()}</dd></div><div><dt>Resolution</dt><dd>{projectFile || model.format === "project_json" ? "Not applicable to project JSON" : model.resolution ?? "Unknown"}</dd></div><div><dt>File size</dt><dd className="rh-mono">{bytes != null ? `${bytes.toLocaleString("en-US")} bytes` : "Available after export"}</dd></div></dl>
          {!done && model.estimate ? <Ledger heading="Render cost">{model.estimate.lines.map((line, index) => <LedgerRow key={index} label={lineLabel(line, "estimate")} amount={formatCents(line.priceCents)} />)}<LedgerTotal label="Estimated total" amountCents={model.estimate.estimateCents} /><CapRow capCents={model.estimate.capCents} /></Ledger> : null}
          {!done ? <div className="rh-notice"><h3 className="rh-h3">Rendering isn’t connected yet.</h3><p className="rh-fg2">You can download your editable project JSON. It does not contain a rendered film.</p>{error ? <p className="rh-fg3 rh-small">Could not load server export details. Your project download is still available.</p> : null}</div> : null}
        </>}
      </div>
      <footer>{done && download ? <a className="rh-btn rh-btn-solid rh-btn-lg" href={download} download={filename}><Download size={15} aria-hidden="true" />Download {projectFile ? "project JSON" : "file"}</a> : <button className="rh-btn rh-btn-solid rh-btn-lg" type="button" onClick={prepareProject} disabled={!model}><FileJson size={15} aria-hidden="true" />Prepare project JSON</button>}<p className="rh-fg3 rh-small">{projectFile ? "No render was started. No credit was used." : "A paid render will require an estimate and hard cap before approval."}</p></footer>
    </DialogPrimitive.Content></DialogPortal>
  </Dialog>;
}
