"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQueryClient,
  type QueryKey,
  type UseMutationResult,
} from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";

/**
 * A mutation that reports its own outcome.
 *
 * Errors are surfaced as a toast carrying the *server's* message. The backend
 * writes those for the caller -- "this batch is full", "a course with that
 * code already exists" -- and replacing them with a generic failure hides the
 * one sentence that says what to do next.
 */
export function useApiMutation<TData, TVariables>(options: {
  mutationFn: (variables: TVariables) => Promise<TData>;
  success?: string | ((data: TData, variables: TVariables) => string);
  invalidate?: QueryKey[];
  onSuccess?: (data: TData, variables: TVariables) => void;
  /** Handle the error yourself (e.g. map it onto form fields). */
  onError?: (error: ApiError, variables: TVariables) => void;
}): UseMutationResult<TData, ApiError, TVariables> {
  const queryClient = useQueryClient();

  return useMutation<TData, ApiError, TVariables>({
    mutationFn: options.mutationFn,
    onSuccess: (data, variables) => {
      for (const key of options.invalidate ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      if (options.success) {
        toast.success(
          typeof options.success === "function"
            ? options.success(data, variables)
            : options.success,
        );
      }
      options.onSuccess?.(data, variables);
    },
    onError: (error, variables) => {
      if (options.onError) {
        options.onError(error, variables);
        return;
      }
      toast.error(error.message);
    },
  });
}

export interface ListState {
  limit: number;
  offset: number;
}

/**
 * Paging plus a debounced search term.
 *
 * Changing the term resets the offset -- staying on page 4 of a result set
 * that now has two rows shows an empty table and looks like a bug.
 */
export function useListState(initialLimit = 25): {
  limit: number;
  offset: number;
  search: string;
  debouncedSearch: string;
  setSearch: (value: string) => void;
  setPage: (next: ListState) => void;
  resetPage: () => void;
} {
  const [limit, setLimit] = useState(initialLimit);
  const [offset, setOffset] = useState(0);
  const [search, setSearchValue] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const setSearch = useCallback((value: string) => {
    setSearchValue(value);
    setOffset(0);
  }, []);

  const setPage = useCallback((next: ListState) => {
    setLimit(next.limit);
    setOffset(next.offset);
  }, []);

  const resetPage = useCallback(() => setOffset(0), []);

  return useMemo(
    () => ({ limit, offset, search, debouncedSearch, setSearch, setPage, resetPage }),
    [limit, offset, search, debouncedSearch, setSearch, setPage, resetPage],
  );
}

/** Apply a rejected request's per-field messages to a react-hook-form. */
export function applyFieldErrors<T extends Record<string, unknown>>(
  error: ApiError,
  setError: (name: keyof T & string, error: { message: string }) => void,
  known: readonly (keyof T & string)[],
): boolean {
  const fields = error.fieldErrors();
  let applied = false;
  for (const [key, message] of Object.entries(fields)) {
    if ((known as readonly string[]).includes(key)) {
      setError(key as keyof T & string, { message });
      applied = true;
    }
  }
  return applied;
}
