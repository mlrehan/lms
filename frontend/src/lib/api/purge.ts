"use client";

/**
 * The permanent-deletion and system-reset endpoints.
 *
 * Kept in its own module rather than added to the generated `types.ts`,
 * because every one of these calls is irreversible and the shapes are read
 * alongside the warnings that explain them.
 *
 * **Nothing here is cached.** `staleTime: 0` and no `gcTime` retention on the
 * preview: a dependency count is only true at the moment it was measured, and
 * a stale figure is the one thing that must never appear on this screen. The
 * server recomputes the plan on execute for the same reason, so a confirmation
 * typed against an old count is refused rather than honoured.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api/client";

export interface PurgeEntityOption {
  key: string;
  label: string;
  /** For counts of one. "1 people" reads as a bug and costs trust in the figure. */
  singular: string;
  consequence: string;
}

export interface PurgeBlockedEntity {
  key: string;
  label: string;
  reason: string;
}

export interface PurgeEntitiesResponse {
  entities: PurgeEntityOption[];
  blocked: PurgeBlockedEntity[];
  unsupported_constraints: string[];
}

export interface PurgeTarget {
  id: number;
  label: string | null;
}

export interface PurgeDependencyRow {
  table: string;
  column: string;
  /** 'cascade' and 'blocks' are both deletions; 'detach' survives. */
  effect: "cascade" | "blocks" | "detach";
  rows: number;
  depth: number;
}

export interface PurgePreviewResponse {
  entity: string;
  label: string;
  singular: string;
  consequence: string;
  requested: number;
  found: number;
  targets: PurgeTarget[];
  deleted_rows: number;
  detached_rows: number;
  breakdown: PurgeDependencyRow[];
  detached_breakdown: PurgeDependencyRow[];
  truncated: boolean;
  blockers: string[];
  confirmation_phrase: string;
}

export interface EmptyBatchRow {
  id: number;
  batch_code: string | null;
  start_date: string | null;
  sessions: number;
}

export interface SystemResetImpact {
  table: string;
  label: string;
  rows: number;
}

export interface SystemResetPreviewResponse {
  database: string;
  environment: string;
  enabled: boolean;
  blockers: string[];
  impact: SystemResetImpact[];
  total_rows: number;
  preserved: string[];
  confirmation_phrase: string;
}

export interface SystemResetResponse {
  database: string;
  rows_deleted: number;
  cleared: SystemResetImpact[];
  seeded: Record<string, unknown>;
  bootstrap_username: string;
  bootstrap_password: string;
  sessions_invalidated: number;
  warnings: string[];
}

export function usePurgeEntities(): UseQueryResult<PurgeEntitiesResponse, ApiError> {
  return useQuery<PurgeEntitiesResponse, ApiError>({
    queryKey: ["purge-entities"],
    queryFn: () => api.get<PurgeEntitiesResponse>("/admin/purge/entities"),
  });
}

export function useEmptyBatches(enabled: boolean): UseQueryResult<EmptyBatchRow[], ApiError> {
  return useQuery<EmptyBatchRow[], ApiError>({
    queryKey: ["purge-empty-batches"],
    queryFn: async () =>
      (await api.get<{ batches: EmptyBatchRow[] }>("/admin/purge/empty-batches")).batches,
    enabled,
    staleTime: 0,
  });
}

export function useSystemResetPreview(): UseQueryResult<SystemResetPreviewResponse, ApiError> {
  return useQuery<SystemResetPreviewResponse, ApiError>({
    queryKey: ["system-reset-preview"],
    queryFn: () => api.get<SystemResetPreviewResponse>("/admin/reset/preview"),
    // Always refetched: the blockers include a running synchronisation, which
    // starts and finishes while this page is open.
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/**
 * The preview. A mutation rather than a query, deliberately: it must run when
 * somebody asks for it and never from a cache, a refocus or a retry.
 */
export function usePurgePreview(): UseMutationResult<
  PurgePreviewResponse,
  ApiError,
  { entity: string; ids: number[] }
> {
  return useMutation<PurgePreviewResponse, ApiError, { entity: string; ids: number[] }>({
    mutationFn: (body) => api.post<PurgePreviewResponse>("/admin/purge/preview", { body }),
  });
}

export function usePurgeExecute(): UseMutationResult<
  PurgePreviewResponse,
  ApiError,
  { entity: string; ids: number[]; confirmation: string }
> {
  return useMutation<
    PurgePreviewResponse,
    ApiError,
    { entity: string; ids: number[]; confirmation: string }
  >({
    mutationFn: (body) => api.post<PurgePreviewResponse>("/admin/purge/execute", { body }),
  });
}

export function useSystemResetExecute(): UseMutationResult<
  SystemResetResponse,
  ApiError,
  { confirmation: string }
> {
  return useMutation<SystemResetResponse, ApiError, { confirmation: string }>({
    mutationFn: (body) => api.post<SystemResetResponse>("/admin/reset/execute", { body }),
  });
}

/**
 * Ids typed or pasted by a person: commas, spaces, newlines, one per line.
 *
 * Returns the ids it understood and the fragments it did not, so the screen
 * can say "3 of these were not numbers" rather than silently dropping them --
 * a dropped id on this screen means somebody believes a record was deleted
 * when it was not.
 */
export function parseIds(raw: string): { ids: number[]; rejected: string[] } {
  const ids: number[] = [];
  const rejected: string[] = [];
  const seen = new Set<number>();

  for (const piece of raw.split(/[\s,;]+/)) {
    if (!piece) continue;
    // `Number` alone accepts "1e3", "0x10" and " 12 ", none of which anybody
    // means when typing a record id.
    if (!/^\d+$/.test(piece)) {
      rejected.push(piece);
      continue;
    }
    const value = Number(piece);
    if (!Number.isSafeInteger(value) || value <= 0) {
      rejected.push(piece);
      continue;
    }
    if (!seen.has(value)) {
      seen.add(value);
      ids.push(value);
    }
  }
  return { ids, rejected };
}
