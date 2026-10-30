"use client";

import { useMemo } from "react";
import { Background, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Band, Disruption } from "@/lib/types";

const STYLE: Record<Band, { border: string; bg: string; text: string }> = {
  high: { border: "#e5384f", bg: "#fdecee", text: "#9b1c2e" },
  medium: { border: "#f59e0b", bg: "#fff6e5", text: "#8a5a00" },
  low: { border: "#16a34a", bg: "#e8f6ec", text: "#14602f" },
  info: { border: "#6b7280", bg: "#f3f4f6", text: "#374151" },
};

export function RippleMap({ data }: { data: Disruption["ripple"] }) {
  const { nodes, edges } = useMemo(() => {
    const ns: Node[] = data.nodes.map((n) => {
      const s = STYLE[n.band];
      return {
        id: n.id,
        position: { x: n.col * 158, y: n.row * 58 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        draggable: false,
        selectable: false,
        data: {
          label: (
            <div className="leading-tight">
              <div className="text-[11px] font-semibold">{n.label}</div>
              {n.sub && <div className="text-[10px] opacity-75">{n.sub}</div>}
            </div>
          ),
        },
        style: {
          width: 128, padding: "6px 8px", borderRadius: 10, border: `1.5px solid ${s.border}`,
          background: s.bg, color: s.text, textAlign: "left",
        },
      };
    });
    const bandOf = new Map(data.nodes.map((n) => [n.id, n.band]));
    const es: Edge[] = data.edges.map(([a, b]) => {
      const risky = bandOf.get(b) === "high";
      return {
        id: `${a}-${b}`, source: a, target: b, type: "smoothstep", animated: risky,
        markerEnd: { type: MarkerType.ArrowClosed, color: risky ? "#e5384f" : "#9ca3af" },
        style: { stroke: risky ? "#e5384f" : "#9ca3af", strokeWidth: 1.5 },
      };
    });
    return { nodes: ns, edges: es };
  }, [data]);

  return (
    <div className="w-full overflow-hidden rounded-2xl bg-[#f4f6f4]" style={{ height: Math.max(250, (Math.max(...data.nodes.map((n) => n.row)) + 1) * 58 + 40) }}>
      <ReactFlow
        key={data.nodes.map((n) => n.id).join("")}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        panOnDrag={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} size={1} color="#dfe5df" />
      </ReactFlow>
    </div>
  );
}
