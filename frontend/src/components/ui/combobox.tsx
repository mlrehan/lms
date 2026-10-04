"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Combobox as BaseCombobox } from "@base-ui/react/combobox";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { controlClasses } from "@/components/ui/form";
import { InlineSpinner } from "@/components/ui/states";
import type { SelectOption } from "@/components/ui/select";
import { cn } from "@/lib/utils";

/**
 * A searchable value selector.
 *
 * `Select` is right for a handful of predefined options; this is for the list
 * long enough that somebody would rather type than scroll. `AsyncCombobox`
 * (below) is the same control over a server-backed list.
 *
 * **Selected labels are remembered, not looked up in the current results.**
 * The hard part of an async picker is that the chosen item frequently is *not*
 * in the options currently loaded — the search box now holds a different term,
 * or the result page has moved on. A control that derives its label purely
 * from `options` shows a raw id the moment that happens. So every label seen
 * is cached by value, and the trigger reads from that cache first. This is
 * what the brief means by "preserve selected values during async result
 * changes", and it is the one behaviour that cannot be bolted on afterwards.
 */

const popupClasses = cn(
  "max-h-(--available-height) w-(--anchor-width) min-w-(--anchor-width) overflow-y-auto scrollbar-thin",
  "origin-(--transform-origin) rounded-lg border border-border-subtle bg-overlay p-1 shadow-overlay",
  "data-[open]:animate-[lms-fade-in_120ms_ease-out] data-[closed]:animate-[lms-fade-out_100ms_ease-in]",
);

const itemClasses = cn(
  "flex cursor-default select-none items-start gap-2 rounded-md px-2 py-1.5 text-sm outline-none",
  "transition-colors duration-150 ease-out",
  "data-[highlighted]:bg-muted data-[highlighted]:text-foreground",
  "data-[disabled]:pointer-events-none data-[disabled]:opacity-45",
);

/** Debounce a search term before it reaches the network. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/**
 * Remembers the label of values that have been *chosen*.
 *
 * The problem this solves: an async list's `options` are whatever the last
 * search returned, so the chosen item is frequently absent from them and a
 * control that reads its label out of `options` shows a raw id.
 *
 * It is filled in the selection handler — an event — rather than during
 * render. An earlier version accumulated into a ref while rendering, which the
 * React Compiler correctly rejects: a render may be thrown away or replayed,
 * so a side effect in one is not guaranteed to have happened (or to have
 * happened once). Recording at the moment of choice is both sound and a
 * smaller claim: the archive only ever needs the values somebody picked.
 */
function useChosenLabels<T extends string>() {
  const [archive, setArchive] = useState<ReadonlyMap<T, SelectOption<T>>>(() => new Map());
  const remember = (options: readonly SelectOption<T>[]) => {
    if (options.length === 0) return;
    setArchive((previous) => {
      const next = new Map(previous);
      for (const option of options) next.set(option.value, option);
      return next;
    });
  };
  return { archive, remember };
}

/** Current options first, then anything previously chosen. */
function lookup<T extends string>(
  value: T,
  options: readonly SelectOption<T>[],
  archive: ReadonlyMap<T, SelectOption<T>>,
): SelectOption<T> | null {
  return options.find((option) => option.value === value) ?? archive.get(value) ?? null;
}

function labelOf<T extends string>(
  item: unknown,
  options: readonly SelectOption<T>[],
  archive: ReadonlyMap<T, SelectOption<T>>,
): string {
  if (item && typeof item === "object" && "label" in item) {
    return String((item as SelectOption<T>).label);
  }
  const key = item as T;
  return lookup(key, options, archive)?.label ?? String(key ?? "");
}

function OptionRow<T extends string>({ option }: { option: SelectOption<T> }): ReactNode {
  return (
    <>
      {option.icon ? (
        <span className="mt-0.5 shrink-0 [&_svg]:size-4 [&_svg]:opacity-70">{option.icon}</span>
      ) : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{option.label}</span>
        {option.description ? (
          <span className="block truncate text-2xs text-subtle-foreground">
            {option.description}
          </span>
        ) : null}
      </span>
      <BaseCombobox.ItemIndicator className="mt-0.5 shrink-0 text-primary">
        <Check className="size-4" aria-hidden />
      </BaseCombobox.ItemIndicator>
    </>
  );
}

function ListBody<T extends string>({
  options,
  loading,
  error,
  onRetry,
  emptyMessage,
}: {
  options: readonly SelectOption<T>[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  emptyMessage: string;
}): ReactNode {
  if (error) {
    return (
      <div className="px-2 py-4 text-center text-sm">
        <p className="text-danger">{error}</p>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="mt-1 text-2xs font-medium text-primary hover:underline"
          >
            Try again
          </button>
        ) : null}
      </div>
    );
  }

  // Loading is only shown when there is nothing to show *yet*. While refining
  // a search the previous results stay on screen, because replacing them with
  // a spinner on every keystroke makes the list flicker and unreadable.
  if (loading && options.length === 0) {
    return (
      // `role="status"` so the wait is announced. A spinner that only exists
      // visually tells a screen-reader user nothing is happening.
      <div
        role="status"
        aria-live="polite"
        aria-label="Loading options"
        className="flex justify-center px-2 py-5"
      >
        <InlineSpinner />
        <span className="sr-only">Loading options…</span>
      </div>
    );
  }

  return (
    <>
      <BaseCombobox.Empty className="px-2 py-4 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </BaseCombobox.Empty>
      <BaseCombobox.List>
        {(option: SelectOption<T>) => (
          <BaseCombobox.Item
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            className={itemClasses}
          >
            <OptionRow option={option} />
          </BaseCombobox.Item>
        )}
      </BaseCombobox.List>
    </>
  );
}

function Popup({ children }: { children: ReactNode }): ReactNode {
  return (
    <BaseCombobox.Portal>
      {/* `z-50`, matching DropdownMenu and Select, so the popup clears a dialog. */}
      <BaseCombobox.Positioner sideOffset={6} className="z-50 outline-none">
        <BaseCombobox.Popup className={popupClasses}>{children}</BaseCombobox.Popup>
      </BaseCombobox.Positioner>
    </BaseCombobox.Portal>
  );
}

interface CommonProps<T extends string> {
  options: readonly SelectOption<T>[];
  placeholder?: string;
  /** Message when the list is empty, e.g. "No people match that search." */
  emptyMessage?: string;
  disabled?: boolean;
  readOnly?: boolean;
  required?: boolean;
  invalid?: boolean;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** Server-backed search. Supplying it disables client-side filtering. */
  onSearch?: (term: string) => void;
  id?: string;
  name?: string;
  className?: string;
  "aria-describedby"?: string;
  "aria-label"?: string;
}

export interface ComboboxProps<T extends string = string> extends CommonProps<T> {
  value: T | null;
  onValueChange: (value: T | null, option: SelectOption<T> | null) => void;
  clearable?: boolean;
}

export function Combobox<T extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = "Search…",
  emptyMessage = "No matches.",
  clearable = true,
  onSearch,
  loading,
  error,
  onRetry,
  invalid,
  disabled,
  readOnly,
  required,
  id,
  name,
  className,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: ComboboxProps<T>): ReactNode {
  const { archive, remember } = useChosenLabels<T>();
  const [term, setTerm] = useState("");

  const selected = value != null ? lookup(value, options, archive) : null;

  return (
    <BaseCombobox.Root
      items={options as SelectOption<T>[]}
      // `null` hands filtering to the server. Leaving Base UI's matcher on
      // would filter the server's own results a second time and hide rows the
      // server deliberately returned.
      filter={onSearch ? null : undefined}
      value={value}
      onValueChange={(next) => {
        const key = (next as T | null) ?? null;
        const option = key != null ? lookup(key, options, archive) : null;
        if (option) remember([option]);
        onValueChange(key, option);
      }}
      inputValue={term}
      onInputValueChange={(next) => {
        setTerm(next);
        onSearch?.(next);
      }}
      itemToStringLabel={(item: unknown) => labelOf(item, options, archive)}
      disabled={disabled}
      readOnly={readOnly}
      required={required}
      name={name}
    >
      <div className="relative flex items-center">
        <BaseCombobox.Input
          id={id}
          placeholder={selected ? selected.label : placeholder}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          aria-label={ariaLabel}
          className={cn(controlClasses, "h-9 pr-14", className)}
        />
        {clearable && value != null && !disabled && !readOnly ? (
          <BaseCombobox.Clear
            aria-label="Clear selection"
            onClick={() => onValueChange(null, null)}
            className={cn(
              "absolute right-8 rounded-xs p-0.5 text-subtle-foreground",
              "transition-colors duration-150 hover:text-foreground",
              "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
            )}
          >
            <X className="size-3.5" aria-hidden />
          </BaseCombobox.Clear>
        ) : null}
        <BaseCombobox.Trigger
          aria-label="Open"
          disabled={disabled}
          className={cn(
            "absolute right-2 rounded-xs p-0.5 text-subtle-foreground",
            "transition-colors duration-150 hover:text-foreground",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
          )}
        >
          <ChevronsUpDown className="size-4" aria-hidden />
        </BaseCombobox.Trigger>
      </div>
      <Popup>
        <ListBody
          options={options}
          loading={loading}
          error={error}
          onRetry={onRetry}
          emptyMessage={emptyMessage}
        />
      </Popup>
    </BaseCombobox.Root>
  );
}

export interface MultiComboboxProps<T extends string = string> extends CommonProps<T> {
  value: readonly T[];
  onValueChange: (value: T[], options: SelectOption<T>[]) => void;
}

/** Searchable multi-selection, with a removable chip per choice. */
export function MultiCombobox<T extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = "Search…",
  emptyMessage = "No matches.",
  onSearch,
  loading,
  error,
  onRetry,
  invalid,
  disabled,
  readOnly,
  required,
  id,
  name,
  className,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: MultiComboboxProps<T>): ReactNode {
  const { archive, remember } = useChosenLabels<T>();
  const [term, setTerm] = useState("");

  // Chips resolve through the archive as well as the current options, so a
  // selection made before the search term changed keeps its name.
  const chips = useMemo(
    () =>
      value.map(
        (key) => lookup(key, options, archive) ?? ({ value: key, label: String(key) } as SelectOption<T>),
      ),
    [value, options, archive],
  );

  return (
    <BaseCombobox.Root
      multiple
      items={options as SelectOption<T>[]}
      filter={onSearch ? null : undefined}
      value={value as T[]}
      onValueChange={(next) => {
        const keys = (next as T[]) ?? [];
        const chosen = keys.map(
          (key) => lookup(key, options, archive) ?? ({ value: key, label: String(key) } as SelectOption<T>),
        );
        remember(chosen);
        onValueChange(keys, chosen);
      }}
      inputValue={term}
      onInputValueChange={(next) => {
        setTerm(next);
        onSearch?.(next);
      }}
      itemToStringLabel={(item: unknown) => labelOf(item, options, archive)}
      disabled={disabled}
      readOnly={readOnly}
      required={required}
      name={name}
    >
      <BaseCombobox.Chips
        className={cn(
          controlClasses,
          "flex min-h-9 flex-wrap items-center gap-1 py-1",
          className,
        )}
      >
        {chips.map((option) => (
          <BaseCombobox.Chip
            key={option.value}
            className={cn(
              "flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5 text-2xs font-medium",
              "text-foreground",
            )}
          >
            <span className="max-w-40 truncate">{option.label}</span>
            {!disabled && !readOnly ? (
              <BaseCombobox.ChipRemove
                aria-label={`Remove ${option.label}`}
                className="rounded-xs text-subtle-foreground transition-colors hover:text-foreground"
              >
                <X className="size-3" aria-hidden />
              </BaseCombobox.ChipRemove>
            ) : null}
          </BaseCombobox.Chip>
        ))}
        <BaseCombobox.Input
          id={id}
          placeholder={chips.length === 0 ? placeholder : ""}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          aria-label={ariaLabel}
          className="h-6 min-w-24 flex-1 border-0 bg-transparent p-0 text-sm outline-none placeholder:text-subtle-foreground"
        />
      </BaseCombobox.Chips>
      <Popup>
        <ListBody
          options={options}
          loading={loading}
          error={error}
          onRetry={onRetry}
          emptyMessage={emptyMessage}
        />
      </Popup>
    </BaseCombobox.Root>
  );
}
