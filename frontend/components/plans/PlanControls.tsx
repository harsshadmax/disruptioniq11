"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Pencil, Play, Send, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { allowed, CAN } from "@/lib/api/types";
import { rolesLabel, statusLabel, planTitle } from "@/lib/adapt";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** What the controls need from a plan; both the generated API type and the dashboard's view model satisfy it. */
export interface PlanLike {
  id: number; version: number; status: string; feasible: boolean; type: string; params: Record<string, unknown>;
  approver_roles: string[]; executor_roles: string[];
}
type Plan = PlanLike;
type Kind = "propose" | "approve" | "reject" | "execute";
const btn = "flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] font-semibold disabled:opacity-50";

const FIELD: Record<string, { key: string; label: string; hint: string }> = {
  reallocate: { key: "qty", label: "Units to move", hint: "Whole units. The source warehouse keeps its safety stock." },
  alt_supplier: { key: "qty", label: "Units to order", hint: "Whole units from the chosen supplier." },
  expedite: { key: "days_saved", label: "Days to save", hint: "How many days faster the carrier delivers." },
  split: { key: "order_refs", label: "Orders to split", hint: "Order references, separated by commas." },
};

/** Buttons for one plan. Shown only when the role fits, but the server checks every click again. */
export function PlanControls({ plan, role, inFlight }: { plan: Plan; role: string; inFlight: boolean }) {
  const qc = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [modifying, setModifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useMutation({
    mutationFn: (kind: Kind) => api<Plan>(`/plans/${plan.id}/${kind}`, {
      body: kind === "reject" ? { version: plan.version, reason } : { version: plan.version },
    }),
    onSuccess: (p) => {
      setError(null); setRejecting(false); setReason("");
      toast.success(`Plan #${p.id} (${planTitle(p)}) is now ${statusLabel(p.status).toLowerCase()}.`);
      qc.invalidateQueries();
    },
    onError: (e) => {
      setError(e instanceof Error ? e.message : "Action failed");
      qc.invalidateQueries(); // show the current state after a stale version or a blocked attempt
    },
  });

  const canModify = plan.feasible && ((plan.status === "DRAFT" && allowed(CAN.modifyDraft, role))
    || (plan.status === "PROPOSED" && allowed(CAN.modifyProposed, role)));
  const busy = (k: Kind) => run.isPending && run.variables === k;

  let main: React.ReactNode = null;
  if (plan.status === "DRAFT" && plan.feasible) {
    main = allowed(CAN.propose, role) ? (
      <button disabled={inFlight || run.isPending} onClick={() => run.mutate("propose")}
        title={inFlight ? "Another plan for this disruption is already in progress" : "Send this plan for approval"}
        className={`${btn} bg-[#e5384f] text-white`}>
        {busy("propose") ? <Loader2 className="size-3 animate-spin" /> : <Send className="size-3" />} Propose
      </button>
    ) : <Hint>An analyst proposes</Hint>;
  } else if (plan.status === "PROPOSED") {
    main = plan.approver_roles.includes(role) ? (
      <div className="flex gap-2">
        <button disabled={run.isPending} onClick={() => run.mutate("approve")} className={`${btn} bg-[#16a34a] text-white`}>
          {busy("approve") ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />} Approve
        </button>
        <button disabled={run.isPending} onClick={() => { setRejecting(true); setError(null); }} className={`${btn} border border-[#e5384f] text-[#e5384f]`}>
          <X className="size-3" /> Reject
        </button>
      </div>
    ) : <Hint>Waiting for {rolesLabel(plan.approver_roles)}</Hint>;
  } else if (plan.status === "APPROVED") {
    main = plan.executor_roles.includes(role) ? (
      <button disabled={run.isPending} onClick={() => run.mutate("execute")} className={`${btn} bg-[#1c1c1e] text-white`}>
        {busy("execute") ? <Loader2 className="size-3 animate-spin" /> : <Play className="size-3" />} Confirm execution
      </button>
    ) : <Hint>Waiting for {rolesLabel(plan.executor_roles)} to confirm</Hint>;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {canModify && (
          <button disabled={run.isPending} onClick={() => setModifying(true)} className={`${btn} border border-[#d9d9de] text-[#1c1c1e]`}>
            <Pencil className="size-3" /> Modify
          </button>
        )}
        {main}
      </div>
      {rejecting && (
        <div className="mt-2 flex gap-2">
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason for rejecting (required)" aria-label="Reason for rejecting"
            className="h-8 flex-1 rounded-lg border border-[#e0e0e4] bg-[#f6f6f7] px-3 text-xs outline-none focus:border-[#e5384f]" />
          <button disabled={reason.trim().length < 3 || run.isPending} onClick={() => run.mutate("reject")} className={`${btn} bg-[#e5384f] text-white`}>Confirm reject</button>
        </div>
      )}
      {error && <div role="alert" className="mt-2 rounded-lg bg-[#fdecee] px-3 py-2 text-[11px] text-[#9b1c2e]">{error}</div>}
      {modifying && <ModifyDialog plan={plan} onClose={() => setModifying(false)} />}
    </div>
  );
}

function ModifyDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const qc = useQueryClient();
  const f = FIELD[plan.type];
  const current = (plan.params as Record<string, unknown>)[f.key];
  const [value, setValue] = useState(Array.isArray(current) ? current.join(", ") : String(current ?? ""));
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      const v = f.key === "order_refs" ? value.split(",").map((s) => s.trim()).filter(Boolean) : Number(value);
      return api<Plan>(`/plans/${plan.id}/modify`, { body: { version: plan.version, changes: { [f.key]: v } } });
    },
    onSuccess: (p) => {
      toast.success(`Plan #${p.id} updated to version ${p.version}. Numbers were recomputed by the rules.`);
      qc.invalidateQueries();
      onClose();
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not modify"),
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Modify: {planTitle(plan)}</DialogTitle>
          <DialogDescription>The rules recompute cost, orders saved and steps. You cannot approve a plan you modified.</DialogDescription>
        </DialogHeader>
        <label className="text-xs font-medium" htmlFor="mod-value">{f.label}</label>
        <input id="mod-value" value={value} onChange={(e) => setValue(e.target.value)} inputMode={f.key === "order_refs" ? "text" : "numeric"}
          className="h-10 rounded-lg border bg-[#f6f6f7] px-3 text-sm outline-none focus:border-[#e5384f]" />
        <p className="text-[11px] text-[#8a8a8f]">{f.hint}</p>
        {error && <div role="alert" className="rounded-lg bg-[#fdecee] px-3 py-2 text-xs text-[#9b1c2e]">{error}</div>}
        <DialogFooter>
          <button onClick={onClose} className={`${btn} border border-[#d9d9de]`}>Cancel</button>
          <button disabled={save.isPending || !value.trim()} onClick={() => save.mutate()} className={`${btn} bg-[#e5384f] text-white`}>
            {save.isPending && <Loader2 className="size-3 animate-spin" />} Save new version
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <span className="text-[10px] text-[#8a8a8f]">{children}</span>;
}
