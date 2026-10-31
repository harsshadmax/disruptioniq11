"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { runDetection } from "@/lib/api";

/** One detection run, shared by the top bar button and the sidebar action. */
export function useRunDetection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runDetection,
    onSuccess: (r) => {
      if (r.created.length + r.updated.length + r.resolved.length === 0) {
        const n = r.unchanged.length;
        toast.info("Detection ran: nothing new.", {
          description: `${n === 0 ? "No active disruptions" : `${n} active disruption${n === 1 ? "" : "s"} re-checked, no change`}. Detection only finds something when shipment, stock or order data changes.`,
        });
      } else {
        toast.success(`Detection finished: ${r.created.length} new, ${r.updated.length} updated, ${r.resolved.length} resolved.`);
      }
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Detection failed"),
  });
}
