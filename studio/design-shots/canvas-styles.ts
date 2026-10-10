import { expect, type Page } from "@playwright/test";

export async function canvasStyles(page: Page, enforceStudioOverrides: boolean) {
  const edge = page.locator(".react-flow__edge-path").first();
  await edge.waitFor({ state: "attached" });
  await expect(edge).toHaveAttribute("d", /^M.+C.+/);
  const observed = await page.evaluate(() => {
    const style = (selector: string) => getComputedStyle(document.querySelector(selector)!);
    const token = (name: string) => {
      const probe = document.createElement("span");
      probe.style.color = `var(${name})`;
      document.body.append(probe);
      const value = getComputedStyle(probe).color;
      probe.remove();
      return value;
    };
    const node = style(".react-flow__node");
    const minimap = style(".react-flow__minimap");
    const handle = style(".react-flow__handle");
    return {
      node: { background: node.backgroundColor, borderWidth: node.borderWidth, padding: node.padding, overflow: node.overflow },
      handle: { background: handle.backgroundColor, borderColor: handle.borderColor, borderWidth: handle.borderWidth, width: handle.width, height: handle.height },
      edge: { stroke: style(".react-flow__edge-path").stroke, width: style(".react-flow__edge-path").strokeWidth },
      minimap: { background: minimap.backgroundColor, borderColor: minimap.borderColor, width: minimap.width, height: minimap.height, marginBottom: minimap.marginBottom },
      controlsZ: style(".canvas-controls").zIndex,
      headerZ: style(".chrome-header").zIndex,
      railZ: style(".tool-rail").zIndex,
      attribution: document.querySelectorAll(".react-flow__attribution").length,
      tokens: { node: token("--node"), line: token("--line"), muted: token("--muted") },
    };
  });
  expect(observed.node).toEqual({ background: "rgba(0, 0, 0, 0)", borderWidth: "0px", padding: "0px", overflow: "visible" });
  expect(observed.handle).toMatchObject({ background: observed.tokens.muted, borderColor: observed.tokens.node, borderWidth: "2px" });
  if (enforceStudioOverrides) {
    expect([observed.handle.width, observed.handle.height]).toEqual(["10px", "10px"]);
    expect(observed.edge).toEqual({ stroke: observed.tokens.muted, width: "1.5px" });
  }
  expect(observed.minimap).toEqual({ background: observed.tokens.node, borderColor: observed.tokens.line, width: "158px", height: "96px", marginBottom: "73px" });
  expect([observed.controlsZ, observed.headerZ, observed.railZ, observed.attribution]).toEqual(["5", "40", "30", 0]);
  return observed;
}
