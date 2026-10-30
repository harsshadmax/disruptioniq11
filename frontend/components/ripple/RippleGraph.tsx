"use client";

import { useMemo, useState } from "react";
import { Background, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { RotateCcw } from "lucide-react";
import type { DisruptionDetail, RankedOrder } from "@/lib/api/types";

type BandName = "high" | "medium" | "low" | "info";
const COLOR: Record<BandName, { border: string; bg: string; text: string }> = {
  high: { border: "#e5384f", bg: "#fdecee", text: "#9b1c2e" },
  medium: { border: "#f59e0b", bg: "#fff6e5", text: "#8a5a00" },
  low: { border: "#16a34a", bg: "#e8f6ec", text: "#14602f" },
  info: { border: "#9ca3af", bg: "#f3f4f6", text: "#374151" },
};
const RANK: Record<BandName, number> = { info: 0, low: 1, medium: 2, high: 3 };

const COL_W = 196;
const ROW_H = 64;
const STEP_MS = 380; // delay between columns: the spread from the delayed shipment outwards
const MAX_ORDERS = 10;

type RippleData = { label: string; sub?: string; band: BandName; stage: number; onPick?: () => void; hint?: string };

function toBand(b: string | null | undefined): BandName {
  return b === "high" || b === "medium" || b === "low" ? b : "info";
}

function RippleNodeView({ data }: NodeProps<Node<RippleData>>) {
  const c = COLOR[data.band];
  const body = (
    <>
      <div className="text-[11px] font-semibold leading-tight">{data.label}</div>
      {data.sub && <div className="text-[10px] leading-tight opacity-75">{data.sub}</div>}
    </>
  );
  const style = {
    width: 150, borderRadius: 10, border: `1.5px solid ${c.border}`, background: c.bg, color: c.text,
    animationDelay: `${data.stage * STEP_MS}ms`,
  };
  return (
    <>
      <Handle type="target" position={Position.Left} className="!size-1 !border-0 !bg-transparent" />
      {data.onPick ? (
        <button type="button" onClick={data.onPick} aria-label={data.hint} title={data.hint}
          className="ripple-in nodrag nopan block cursor-pointer px-2 py-1.5 text-left transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#e5384f]"
          style={style}>{body}</button>
      ) : (
        <div className="ripple-in px-2 py-1.5 text-left" style={style}>{body}</div>
      )}
      <Handle type="source" position={Position.Right} className="!size-1 !border-0 !bg-transparent" />
    </>
  );
}
const nodeTypes = { ripple: RippleNodeView };

function build(d: DisruptionDetail, orders: RankedOrder[], onPick: (o: RankedOrder) => void) {
  const shown = orders.slice(0, MAX_ORDERS);
  const nodes: Node<RippleData>[] = [];
  const edges: [string, string, number][] = []; // source, target, stage of the target
  const sev = toBand(d.severity);
  let stage = 0;
  const col = () => stage++;
  const mid = Math.max(0, (shown.length - 1) / 2);
  const add = (id: string, x: number, row: number, data: RippleData) =>
    nodes.push({ id, type: "ripple", position: { x: x * COL_W, y: row * ROW_H }, data, draggable: false, selectable: false });

  const lateDays = d.promised_eta && d.current_eta
    ? Math.round((+new Date(d.current_eta) - +new Date(d.promised_eta)) / 86400000) : 0;
  let prev: string | null = null;
  const chain = (id: string, data: Omit<RippleData, "stage">) => {
    const s = col();
    add(id, s, mid, { ...data, stage: s });
    if (prev) edges.push([prev, id, s]);
    prev = id;
  };

  if (d.shipment_ref) {
    chain("shipment", {
      label: d.shipment_ref, band: sev,
      sub: [d.supplier, lateDays > 0 ? `${lateDays} days late` : d.type === "stock_shortage" ? "partial delivery" : null].filter(Boolean).join(" · "),
    });
  }
  chain("warehouse", { label: `${d.warehouse} warehouse`, sub: "stock arrives late", band: sev });
  chain("sku", { label: d.sku_code, sub: d.sku_name, band: sev });

  const orderStage = col();
  shown.forEach((o, i) => {
    add(`o${o.order_id}`, orderStage, i, {
      label: `${o.order_ref} · ${o.tier}`, sub: `risk ${o.score.toFixed(0)} · short ${o.uncovered_qty} of ${o.order_qty}`,
      band: toBand(o.band), stage: orderStage, onPick: () => onPick(o), hint: `Why is ${o.order_ref} ranked #${o.rank}?`,
    });
    edges.push(["sku", `o${o.order_id}`, orderStage]);
  });

  const custStage = col();
  const byCustomer = new Map<string, { rows: number[]; band: BandName; ids: string[] }>();
  shown.forEach((o, i) => {
    const e = byCustomer.get(o.customer) ?? { rows: [], band: "info" as BandName, ids: [] };
    e.rows.push(i);
    e.ids.push(`o${o.order_id}`);
    if (RANK[toBand(o.band)] > RANK[e.band]) e.band = toBand(o.band);
    byCustomer.set(o.customer, e);
  });
  [...byCustomer.entries()].forEach(([name, e], i) => {
    const row = e.rows.reduce((a, b) => a + b, 0) / e.rows.length;
    add(`c${i}`, custStage, row, { label: name, sub: e.rows.length > 1 ? `${e.rows.length} orders` : "customer", band: e.band, stage: custStage });
    e.ids.forEach((oid) => edges.push([oid, `c${i}`, custStage]));
  });

  const bandOf = new Map(nodes.map((n) => [n.id, n.data.band]));
  const flowEdges: Edge[] = edges.map(([a, b, s]) => {
    const hot = bandOf.get(b) === "high";
    const color = hot ? "#e5384f" : "#b4b8be";
    return {
      id: `${a}>${b}`, source: a, target: b, type: "smoothstep", animated: hot,
      markerEnd: { type: MarkerType.ArrowClosed, color },
      className: `ripple-edge ripple-edge-${s}`, // fades in with its target column; keeps the dash flow on risky edges
      style: { stroke: color, strokeWidth: 1.5 },
    };
  });
  const rows = Math.max(shown.length, byCustomer.size, 1);
  return { nodes, edges: flowEdges, height: Math.max(260, rows * ROW_H + 60), hidden: Math.max(0, orders.length - shown.length) };
}

export function RippleGraph({ d, orders, onSelectOrder }: { d: DisruptionDetail; orders: RankedOrder[]; onSelectOrder: (o: RankedOrder) => void }) {
  const [run, setRun] = useState(0); // changing the key re-mounts the graph, which replays the spread
  const g = useMemo(() => build(d, orders, onSelectOrder), [d, orders, onSelectOrder]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-3 text-[10px] text-[#6b6b70]">
        {(["high", "medium", "low"] as const).map((b) => (
          <span key={b} className="flex items-center gap-1"><span className="size-2 rounded-full" style={{ background: COLOR[b].border }} />{b[0].toUpperCase() + b.slice(1)} risk</span>
        ))}
        <span>Click an order to see why it is ranked where it is.</span>
        <button type="button" onClick={() => setRun((n) => n + 1)} className="ml-auto flex items-center gap-1 text-[#e5384f]"><RotateCcw className="size-3" /> Replay</button>
      </div>
      <div className="w-full overflow-hidden rounded-2xl bg-[#f4f6f4]" style={{ height: g.height }}>
        <ReactFlow key={`${d.id}-${run}`} nodes={g.nodes} edges={g.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.1 }}
          nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} zoomOnScroll={false} zoomOnPinch={false}
          zoomOnDoubleClick={false} panOnDrag={false} preventScrolling={false} proOptions={{ hideAttribution: true }}>
          <Background gap={18} size={1} color="#dfe5df" />
        </ReactFlow>
      </div>
      {g.hidden > 0 && <p className="mt-2 text-[10px] text-[#8a8a8f]">Showing the {MAX_ORDERS} highest-ranked orders; {g.hidden} more are in the table below.</p>}
    </div>
  );
}
