import type { Connection, Edge, Node } from "@xyflow/react";
import type { CanvasEdgeData, CanvasNodeData, CreativeNodeKind, PortDataType } from "./types";
import { portsForNode, portDataTypeLabel } from "./tool-registry";

export type CanvasNode = Node<CanvasNodeData, CreativeNodeKind>;
export type CanvasEdge = Edge<CanvasEdgeData>;

export function isCompatibleConnection(
  connection: Connection | Edge,
  nodes: CanvasNode[],
): { ok: true; dataType: PortDataType; targetField: string } | { ok: false; reason: string } {
  const source = nodes.find((node) => node.id === connection.source);
  const target = nodes.find((node) => node.id === connection.target);
  if (!source || !target) {
    return { ok: false, reason: "Connect two nodes on the canvas." };
  }
  if (source.id === target.id) {
    return { ok: false, reason: "A node cannot connect to itself." };
  }
  const sourcePorts = portsForNode(source.data.toolId, source.data.kind).outputs;
  const targetPorts = portsForNode(target.data.toolId, target.data.kind).inputs;
  const sourcePort = sourcePorts.find((port) => port.id === (connection.sourceHandle || sourcePorts[0]?.id));
  const targetPort = targetPorts.find((port) => port.id === (connection.targetHandle || targetPorts[0]?.id));
  if (!sourcePort || !targetPort) {
    return { ok: false, reason: "That handle does not accept a connection." };
  }
  if (sourcePort.dataType !== targetPort.dataType) {
    return {
      ok: false,
      reason: `This input expects ${portDataTypeLabel(targetPort.dataType)}, not ${portDataTypeLabel(sourcePort.dataType)}.`,
    };
  }
  if (!targetPort.targetField) {
    return { ok: false, reason: "That input is not wired to a setting." };
  }
  return { ok: true, dataType: sourcePort.dataType, targetField: targetPort.targetField };
}

export function edgeAlreadyOccupiesHandle(edges: CanvasEdge[], connection: Connection): boolean {
  return edges.some(
    (edge) =>
      edge.target === connection.target &&
      (edge.targetHandle || "") === (connection.targetHandle || ""),
  );
}
