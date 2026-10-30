"use client";

import Link from "next/link";
import { useMemo } from "react";
import { Background, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Band, Disruption } from "@/lib/types";

const STYLE: Record<Band, { border: string; bg: string; text: string }> = {
  high: { border: "#c8352b", bg: "#f8e4e1", text: "#8c2a22" },
  medium: { border: "#c77700", bg: "#f8ecd3", text: "#8a5a00" },
  low: { border: "#2e7d4f", bg: "#e3f0e7", text: "#1f5a3a" },
  info: { border: "#6b7280", bg: "#efece6", text: "#374151" },
};

/** Order boxes link to the disruption page, which opens that order's "Why is it ranked here?" panel. */
export function RippleMap({ data, disruptionId }: { data: Disruption["ripple"]; disruptionId: number }) {
  const { nodes, edges } = useMemo(() => {
    const ns: Node[] = data.nodes.map((n) => {
      const s = STYLE[n.band];
      const text = (
        <>
          <div className="text-[11px] font-semibold">{n.label}</div>
          {n.sub && <div className="text-[10px] opacity-75">{n.sub}</div>}
        </>
      );
      return {
        id: n.id,
        position: { x: n.col * 158, y: n.row * 58 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        draggable: false,
        selectable: false,
        data: {
          label: n.orderId === undefined ? (
            <div className="px-2 py-1.5 leading-tight">{text}</div>
          ) : (
            <Link
              href={`/disruptions/${disruptionId}?order=${n.orderId}`}
              title={`Open ${n.label.split(" · ")[0]} and see why it is ranked here`}
              className="block rounded-[8px] px-2 py-1.5 leading-tight hover:bg-white/60 focus-visible:outline-2 focus-visible:outline-brand"
            >
              {text}
            </Link>
          ),
        },
        style: {
          width: 128, padding: 0, borderRadius: 10, border: `1.5px solid ${s.border}`,
          background: s.bg, color: s.text, textAlign: "left",
          ...(n.orderId === undefined ? {} : { pointerEvents: "all" as const }),
        },
      };
    });
    const bandOf = new Map(data.nodes.map((n) => [n.id, n.band]));
    const es: Edge[] = data.edges.map(([a, b]) => {
      const risky = bandOf.get(b) === "high";
      return {
        id: `${a}-${b}`, source: a, target: b, type: "smoothstep", animated: risky,
        markerEnd: { type: MarkerType.ArrowClosed, color: risky ? "#c8352b" : "#9ca3af" },
        style: { stroke: risky ? "#c8352b" : "#9ca3af", strokeWidth: 1.5 },
      };
    });
    return { nodes: ns, edges: es };
  }, [data, disruptionId]);

  return (
    <div className="w-full overflow-hidden rounded-2xl bg-brand-wash" style={{ height: Math.max(250, (Math.max(...data.nodes.map((n) => n.row)) + 1) * 58 + 40) }}>
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
        <Background gap={18} size={1} color="#d3dfee" />
      </ReactFlow>
    </div>
  );
}
