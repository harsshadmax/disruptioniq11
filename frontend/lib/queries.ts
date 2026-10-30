"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type {
  AuditRow, AuditVerify, DemoTargets, Disruption, DisruptionDetail, ImportResult, Inbox, Plan, RankedOrder,
  SimulationOptions,
} from "@/lib/api/types";

const POLL = 15_000;

export const useDisruptions = (state: "active" | "resolved" | "all" = "active") =>
  useQuery({ queryKey: ["disruptions", state], queryFn: () => api<Disruption[]>("/disruptions", { params: { state } }), refetchInterval: POLL });

export const useDisruption = (id: number) =>
  useQuery({ queryKey: ["disruption", id], queryFn: () => api<DisruptionDetail>(`/disruptions/${id}`), refetchInterval: POLL });

export const useOrders = (id: number) =>
  useQuery({ queryKey: ["orders", id], queryFn: () => api<RankedOrder[]>(`/disruptions/${id}/orders`) });

export const useDisruptionPlans = (id: number) =>
  useQuery({ queryKey: ["plans", "of", id], queryFn: () => api<Plan[]>(`/disruptions/${id}/plans`), refetchInterval: POLL });

export const usePlans = (state?: string) =>
  useQuery({ queryKey: ["plans", "state", state ?? "all"], queryFn: () => api<Plan[]>("/plans", { params: { state } }), refetchInterval: POLL });

export const useInbox = () =>
  useQuery({ queryKey: ["inbox"], queryFn: () => api<Inbox>("/notifications", { params: { limit: 30 } }), refetchInterval: POLL });

export const useAudit = (action: string, entityType: string, enabled: boolean) =>
  useQuery({
    queryKey: ["audit", action, entityType],
    queryFn: () => api<AuditRow[]>("/audit", { params: { action, entity_type: entityType, limit: 200 } }),
    enabled, refetchInterval: POLL,
  });

export const useAuditVerify = (enabled: boolean) =>
  useQuery({ queryKey: ["audit", "verify"], queryFn: () => api<AuditVerify>("/audit/verify"), enabled });

export const useDemoTargets = (enabled: boolean) =>
  useQuery({ queryKey: ["demo", "targets"], queryFn: () => api<DemoTargets>("/demo/targets"), enabled, refetchInterval: POLL });

export const useSimulationOptions = (enabled: boolean) =>
  useQuery({ queryKey: ["simulate", "options"], queryFn: () => api<SimulationOptions>("/simulate/options"), enabled });

export const useBatches = () =>
  useQuery({ queryKey: ["batches"], queryFn: () => api<ImportResult[]>("/import/batches", { params: { limit: 10 } }) });
