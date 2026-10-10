/** Example server responses for design captures and tests only. */
export const exportDisconnected = { state: "disconnected", format: "project_json", resolution: null, size_bytes: null };
export const exportConfigure = {
  state: "configure", format: "mp4", resolution: "720p", size_bytes: 1200000,
  estimate: { estimate_cents: 0, cap_cents: 0, lines: [{ kind: "media", label: "Studio render", price_cents: 0, basis: "fixed" }] },
};
export const exportDone = { state: "done", format: "mp4", resolution: "720p", size_bytes: 1200000, download_path: "/beta/p1-film.mp4" };
