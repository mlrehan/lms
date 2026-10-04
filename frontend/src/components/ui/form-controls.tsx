"use client";

import type { ReactNode } from "react";
import {
  Controller,
  type Control,
  type FieldPath,
  type FieldValues,
} from "react-hook-form";
import { Combobox, type ComboboxProps } from "@/components/ui/combobox";
import { MultiSelect, Select, type SelectOption } from "@/components/ui/select";

/**
 * React Hook Form bindings for the selection controls.
 *
 * Kept out of `select.tsx` and `combobox.tsx` on purpose: those are plain
 * controlled components with no knowledge of any form library, which is what
 * lets them be used in filter bars, toolbars and table footers where there is
 * no form at all. The coupling lives here, in one file, rather than being
 * spread through both.
 *
 * **Why `Controller` and not `register`.** `register` works by spreading
 * `onChange`/`ref`/`name` onto a native element, and these controls are not
 * native elements — they report a *value*, not a change event, and their DOM
 * node is a button or an input that is not the field. A `register`ed Base UI
 * select would silently never update the form. `Controller` is the supported
 * bridge for exactly this case.
 *
 * An empty selection is reported as `null`, and `emptyValue` decides what that
 * becomes in the form state — `""` for a field the API expects as a string,
 * `null` for a nullable one. Guessing here would quietly change what gets
 * submitted.
 */

interface BaseProps<TValues extends FieldValues> {
  control: Control<TValues>;
  name: FieldPath<TValues>;
  options: readonly SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  id?: string;
  "aria-describedby"?: string;
  "aria-label"?: string;
  /** What a cleared selection becomes in form state. Defaults to `""`. */
  emptyValue?: "" | null;
}

export function FormSelect<TValues extends FieldValues>({
  control,
  name,
  options,
  placeholder,
  disabled,
  required,
  id,
  emptyValue = "",
  clearable,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: BaseProps<TValues> & { clearable?: boolean }): ReactNode {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Select
          id={id}
          aria-describedby={describedBy}
          aria-label={ariaLabel}
          value={(field.value as string | null) || null}
          onValueChange={(next) => field.onChange(next ?? emptyValue)}
          options={options}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          clearable={clearable}
          invalid={!!fieldState.error}
        />
      )}
    />
  );
}

export function FormMultiSelect<TValues extends FieldValues>({
  control,
  name,
  options,
  placeholder,
  disabled,
  required,
  id,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: BaseProps<TValues>): ReactNode {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <MultiSelect
          id={id}
          aria-describedby={describedBy}
          aria-label={ariaLabel}
          value={(field.value as string[] | undefined) ?? []}
          onValueChange={(next) => field.onChange(next)}
          options={options}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          invalid={!!fieldState.error}
        />
      )}
    />
  );
}

export function FormCombobox<TValues extends FieldValues>({
  control,
  name,
  emptyValue = "",
  ...rest
}: BaseProps<TValues> &
  Omit<ComboboxProps, "value" | "onValueChange" | "invalid">): ReactNode {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Combobox
          {...rest}
          value={(field.value as string | null) || null}
          onValueChange={(next) => field.onChange(next ?? emptyValue)}
          invalid={!!fieldState.error}
        />
      )}
    />
  );
}
