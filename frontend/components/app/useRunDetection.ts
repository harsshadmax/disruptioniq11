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
      toast.success(`Detection finished: ${r.created.length} new, ${r.updated.length} updated, ${r.resolved.length} resolved.`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Detection failed"),
  });
}
