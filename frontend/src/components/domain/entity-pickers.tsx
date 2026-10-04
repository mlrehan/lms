"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Controller,
  type Control,
  type FieldPath,
  type FieldValues,
} from "react-hook-form";
import { api } from "@/lib/api/client";
import type {
  BatchSummary,
  CourseSummary,
  PageBatchSummary,
  PageCourseSummary,
} from "@/lib/api/types";
import { Combobox, useDebounced } from "@/components/ui/combobox";
import type { SelectOption } from "@/components/ui/select";
import { useSession } from "@/lib/auth/session";

/**
 * Searchable pickers for the two entities the console selects most often.
 *
 * Every one of these used to be a `Select` fed by `limit: 200`, which fails in
 * two ways at once that are easy to miss because neither shows an error: the
 * 201st batch is simply absent from the list with nothing saying so, and
 * finding one of 200 means reading 200 rows because a `Select` cannot be typed
 * into. `/batches` and `/courses` have both accepted a server-side search term
 * all along — `q` and `query` respectively, an inconsistency in the API that
 * this module absorbs so no call site has to know about it.
 *
 * Shaped exactly like `UserPicker`, deliberately: the debounce, the "remember
 * the chosen label" lookup and the loading and error states are the same three
 * problems, and solving them a third and fourth way is how two pickers on one
 * page end up behaving differently.
 */

const PAGE = 20;

/** A preset value carries no label, so it is looked up once and kept. */
function useKnown<T>(path: string, value: string | null, enabled = true) {
  return useQuery({
    queryKey: [path, "label", value],
    queryFn: () => api.get<T>(`${path}/${value}`),
    enabled: enabled && !!value,
    staleTime: 5 * 60_000,
  });
}

export function BatchPicker({
  value,
  onValueChange,
  id,
  disabled,
  placeholder = "Search batches",
  isActive,
  clearable = true,
  ariaLabel = "Search batches",
  className,
}: {
  value: string | null;
  onValueChange: (batchId: string | null, batch: BatchSummary | null) => void;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  /** Restrict to running batches, for a field that only makes sense for one. */
  isActive?: boolean;
  clearable?: boolean;
  ariaLabel?: string;
  className?: string;
}): ReactNode {
  /*
   * The read permission is checked here rather than at each call site. Every
   * screen that used to fetch its own option list gated that query on
   * `batch.read`; folding the gate into the control keeps that behaviour in
   * one place instead of nine, and means a new caller cannot forget it. The
   * server checks it again on every request regardless.
   */
  const { permissions } = useSession();
  const canSearch = permissions.has("batch.read");

  const [term, setTerm] = useState("");
  const debounced = useDebounced(term, 300);

  const search = useQuery({
    queryKey: ["batches", "picker", debounced, isActive ?? null],
    queryFn: () =>
      api.get<PageBatchSummary>("/batches", {
        query: {
          q: debounced || undefined,
          is_active: isActive,
          limit: PAGE,
          sort: "batch_code",
        },
      }),
    enabled: canSearch && !disabled,
    staleTime: 30_000,
  });

  const known = useKnown<BatchSummary>("/batches", value, canSearch && !disabled);

  const byId = useMemo(() => {
    const map = new Map<string, BatchSummary>();
    for (const batch of search.data?.items ?? []) map.set(batch.public_id, batch);
    if (known.data) map.set(known.data.public_id, known.data);
    return map;
  }, [search.data, known.data]);

  const options = useMemo<SelectOption[]>(() => {
    const describe = (batch: BatchSummary) => ({
      value: batch.public_id,
      label: batch.batch_code,
      description:
        [batch.course_title, batch.training_method].filter(Boolean).join(" · ") || undefined,
    });
    const items = search.data?.items ?? [];
    const list = items.map(describe);
    // The selected batch stays in the list even when the current search does
    // not return it, so the control can always name its own value.
    if (known.data && !items.some((batch) => batch.public_id === known.data!.public_id)) {
      list.unshift(describe(known.data));
    }
    return list;
  }, [search.data, known.data]);

  return (
    <Combobox
      id={id}
      className={className}
      value={value}
      disabled={disabled || !canSearch}
      placeholder={canSearch ? placeholder : "You cannot browse batches"}
      aria-label={ariaLabel}
      emptyMessage="No matching batches."
      clearable={clearable}
      options={options}
      loading={search.isFetching}
      error={search.error ? "Could not search batches." : null}
      onRetry={() => void search.refetch()}
      onSearch={setTerm}
      onValueChange={(next) => onValueChange(next, next ? (byId.get(next) ?? null) : null)}
    />
  );
}

export function CoursePicker({
  value,
  onValueChange,
  id,
  disabled,
  placeholder = "Search courses",
  status,
  clearable = true,
  ariaLabel = "Search courses",
  className,
}: {
  value: string | null;
  onValueChange: (courseId: string | null, course: CourseSummary | null) => void;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  /** e.g. `PUBLISHED`, for a field that should not offer a draft. */
  status?: string;
  clearable?: boolean;
  ariaLabel?: string;
  className?: string;
}): ReactNode {
  const { permissions } = useSession();
  const canSearch = permissions.has("course.read");

  const [term, setTerm] = useState("");
  const debounced = useDebounced(term, 300);

  const search = useQuery({
    queryKey: ["courses", "picker", debounced, status ?? null],
    queryFn: () =>
      api.get<PageCourseSummary>("/courses", {
        query: { query: debounced || undefined, status, limit: PAGE },
      }),
    enabled: canSearch && !disabled,
    staleTime: 30_000,
  });

  const known = useKnown<CourseSummary>("/courses", value, canSearch && !disabled);

  const byId = useMemo(() => {
    const map = new Map<string, CourseSummary>();
    for (const course of search.data?.items ?? []) map.set(course.public_id, course);
    if (known.data) map.set(known.data.public_id, known.data);
    return map;
  }, [search.data, known.data]);

  const options = useMemo<SelectOption[]>(() => {
    const describe = (course: CourseSummary) => ({
      value: course.public_id,
      label: course.title,
      description: [course.code, course.level].filter(Boolean).join(" · ") || undefined,
    });
    const items = search.data?.items ?? [];
    const list = items.map(describe);
    if (known.data && !items.some((course) => course.public_id === known.data!.public_id)) {
      list.unshift(describe(known.data));
    }
    return list;
  }, [search.data, known.data]);

  return (
    <Combobox
      id={id}
      className={className}
      value={value}
      disabled={disabled || !canSearch}
      placeholder={canSearch ? placeholder : "You cannot browse courses"}
      aria-label={ariaLabel}
      emptyMessage="No matching courses."
      clearable={clearable}
      options={options}
      loading={search.isFetching}
      error={search.error ? "Could not search courses." : null}
      onRetry={() => void search.refetch()}
      onSearch={setTerm}
      onValueChange={(next) => onValueChange(next, next ? (byId.get(next) ?? null) : null)}
    />
  );
}

/*
 * React Hook Form bindings.
 *
 * These live here rather than in `ui/form-controls.tsx` because they are
 * domain pickers: they know which endpoint to search and what a row is called.
 * `form-controls.tsx` deliberately knows about no endpoint at all.
 */

interface FormPickerProps<TValues extends FieldValues> {
  control: Control<TValues>;
  name: FieldPath<TValues>;
  id?: string;
  disabled?: boolean;
  placeholder?: string;
  clearable?: boolean;
  /** What an empty selection becomes in the form state. */
  emptyValue?: "" | null;
}

export function FormBatchPicker<TValues extends FieldValues>({
  control,
  name,
  emptyValue = "",
  isActive,
  ...rest
}: FormPickerProps<TValues> & { isActive?: boolean }): ReactNode {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <BatchPicker
          {...rest}
          isActive={isActive}
          value={(field.value as string | null) || null}
          onValueChange={(next) => field.onChange(next ?? emptyValue)}
        />
      )}
    />
  );
}

export function FormCoursePicker<TValues extends FieldValues>({
  control,
  name,
  emptyValue = "",
  status,
  ...rest
}: FormPickerProps<TValues> & { status?: string }): ReactNode {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field }) => (
        <CoursePicker
          {...rest}
          status={status}
          value={(field.value as string | null) || null}
          onValueChange={(next) => field.onChange(next ?? emptyValue)}
        />
      )}
    />
  );
}
