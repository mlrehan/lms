"use client";

import type { ReactNode } from "react";
import { Select as BaseSelect } from "@base-ui/react/select";
import { Check, ChevronsUpDown, X } from "lucide-react";
import { controlClasses } from "@/components/ui/form";
import { cn } from "@/lib/utils";

/**
 * The console's value selector for a *known, short* list of options.
 *
 * Use this when the options are predefined and few enough to read at a glance
 * — a status, a role, a visibility mode. When the list is long enough that
 * somebody would want to type, use `Combobox`; when the list comes from the
 * server, use `AsyncCombobox`. When the control performs an *action* rather
 * than choosing a value, it is a `DropdownMenu`, not this.
 *
 * **The label is resolved from `options`, never from the mounted items.**
 * Base UI's `Select.Value` reads the currently-mounted `Select.Item` children
 * to decide what to display, which is correct for a static list and wrong for
 * one that arrives from a query: at first paint no item has mounted, so a
 * pre-selected value renders as its raw id — a UUID where a name belongs —
 * and nothing re-resolves it afterwards. Looking the label up in the `options`
 * array sidesteps the mount timing entirely, so an async-populated select with
 * a preset value is correct on its first frame.
 *
 * Styling comes from `controlClasses`, the same export `Input` uses, so a
 * select and a text field in the same row cannot drift apart.
 */

export interface SelectOption<T extends string = string> {
  value: T;
  label: string;
  /** A second line under the label. Searchable in `Combobox`. */
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
  /** Options sharing a group name are rendered under a heading. */
  group?: string;
}

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
      <BaseSelect.ItemIndicator className="mt-0.5 shrink-0 text-primary">
        <Check className="size-4" aria-hidden />
      </BaseSelect.ItemIndicator>
    </>
  );
}

/** Options rendered in `group` order, with headings, falling back to a flat list. */
function renderOptions<T extends string>(options: readonly SelectOption<T>[]): ReactNode {
  const grouped = options.some((option) => option.group);
  if (!grouped) {
    return options.map((option) => (
      <BaseSelect.Item
        key={option.value}
        value={option.value}
        disabled={option.disabled}
        className={itemClasses}
      >
        <OptionRow option={option} />
      </BaseSelect.Item>
    ));
  }

  const order: string[] = [];
  const byGroup = new Map<string, SelectOption<T>[]>();
  for (const option of options) {
    const key = option.group ?? "";
    if (!byGroup.has(key)) {
      byGroup.set(key, []);
      order.push(key);
    }
    byGroup.get(key)!.push(option);
  }

  return order.map((key) => (
    <BaseSelect.Group key={key || "ungrouped"}>
      {key ? (
        <BaseSelect.GroupLabel className="px-2 pb-1 pt-2 text-2xs font-semibold uppercase tracking-caps text-subtle-foreground">
          {key}
        </BaseSelect.GroupLabel>
      ) : null}
      {byGroup.get(key)!.map((option) => (
        <BaseSelect.Item
          key={option.value}
          value={option.value}
          disabled={option.disabled}
          className={itemClasses}
        >
          <OptionRow option={option} />
        </BaseSelect.Item>
      ))}
    </BaseSelect.Group>
  ));
}

function Popup({ children }: { children: ReactNode }): ReactNode {
  return (
    <BaseSelect.Portal>
      {/*
        `z-50` matches `DropdownMenuContent`, which is what keeps a select
        usable inside a dialog: the dialog's own layer sits below it, so the
        popup is not clipped by the dialog it was opened from.
      */}
      <BaseSelect.Positioner
        sideOffset={6}
        alignItemWithTrigger={false}
        className="z-50 outline-none"
      >
        <BaseSelect.Popup className={popupClasses}>{children}</BaseSelect.Popup>
      </BaseSelect.Positioner>
    </BaseSelect.Portal>
  );
}

interface CommonProps {
  id?: string;
  name?: string;
  placeholder?: string;
  disabled?: boolean;
  readOnly?: boolean;
  required?: boolean;
  className?: string;
  /** Marks the control invalid and recolours its border, matching `Input`. */
  invalid?: boolean;
  "aria-describedby"?: string;
  "aria-label"?: string;
}

function Trigger({
  id,
  disabled,
  readOnly,
  invalid,
  className,
  describedBy,
  ariaLabel,
  children,
  onClear,
}: {
  id?: string;
  disabled?: boolean;
  readOnly?: boolean;
  invalid?: boolean;
  className?: string;
  describedBy?: string;
  ariaLabel?: string;
  children: ReactNode;
  onClear?: () => void;
}): ReactNode {
  return (
    <div className="relative flex items-center">
      <BaseSelect.Trigger
        id={id}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        aria-label={ariaLabel}
        className={cn(
          controlClasses,
          "flex h-9 items-center justify-between gap-2 text-left",
          onClear ? "pr-14" : "pr-8",
          readOnly && "pointer-events-none",
          className,
        )}
      >
        <span className="min-w-0 flex-1 truncate">{children}</span>
        <BaseSelect.Icon className="pointer-events-none absolute right-2.5 text-subtle-foreground">
          <ChevronsUpDown className="size-4" aria-hidden />
        </BaseSelect.Icon>
      </BaseSelect.Trigger>
      {onClear ? (
        // Outside the trigger: a button nested in a button is invalid markup
        // and the inner one never receives the click.
        <button
          type="button"
          aria-label="Clear selection"
          disabled={disabled}
          onClick={onClear}
          className={cn(
            "absolute right-8 rounded-xs p-0.5 text-subtle-foreground",
            "transition-colors duration-150 hover:text-foreground",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
          )}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

export interface SelectProps<T extends string = string> extends CommonProps {
  value: T | null;
  onValueChange: (value: T | null) => void;
  options: readonly SelectOption<T>[];
  /** Shows an X to return to `null`. Omit for a field that must hold a value. */
  clearable?: boolean;
}

export function Select<T extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  clearable = false,
  invalid,
  className,
  id,
  name,
  disabled,
  readOnly,
  required,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: SelectProps<T>): ReactNode {
  const selected = options.find((option) => option.value === value) ?? null;

  return (
    <BaseSelect.Root
      items={options as { label: ReactNode; value: T }[]}
      value={value}
      onValueChange={(next) => onValueChange((next as T | null) ?? null)}
      name={name}
      disabled={disabled}
      readOnly={readOnly}
      required={required}
    >
      <Trigger
        id={id}
        disabled={disabled}
        readOnly={readOnly}
        invalid={invalid}
        className={className}
        describedBy={describedBy}
        ariaLabel={ariaLabel}
        onClear={clearable && value != null && !disabled && !readOnly ? () => onValueChange(null) : undefined}
      >
        {selected ? (
          <span className="flex items-center gap-2">
            {selected.icon ? (
              <span className="shrink-0 [&_svg]:size-4 [&_svg]:opacity-70">{selected.icon}</span>
            ) : null}
            <span className="truncate">{selected.label}</span>
          </span>
        ) : (
          <span className="text-subtle-foreground">{placeholder}</span>
        )}
      </Trigger>
      <Popup>{renderOptions(options)}</Popup>
    </BaseSelect.Root>
  );
}

export interface MultiSelectProps<T extends string = string> extends CommonProps {
  value: readonly T[];
  onValueChange: (value: T[]) => void;
  options: readonly SelectOption<T>[];
  /** How the trigger summarises a selection too long to list. */
  summarise?: (selected: SelectOption<T>[]) => string;
}

export function MultiSelect<T extends string = string>({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  summarise,
  invalid,
  className,
  id,
  name,
  disabled,
  readOnly,
  required,
  "aria-describedby": describedBy,
  "aria-label": ariaLabel,
}: MultiSelectProps<T>): ReactNode {
  const selected = options.filter((option) => value.includes(option.value));
  const label = summarise
    ? summarise(selected)
    : selected.length === 0
      ? null
      : selected.length <= 2
        ? selected.map((option) => option.label).join(", ")
        : `${selected.length} selected`;

  return (
    <BaseSelect.Root
      multiple
      items={options as { label: ReactNode; value: T }[]}
      value={value as T[]}
      onValueChange={(next) => onValueChange((next as T[]) ?? [])}
      name={name}
      disabled={disabled}
      readOnly={readOnly}
      required={required}
    >
      <Trigger
        id={id}
        disabled={disabled}
        readOnly={readOnly}
        invalid={invalid}
        className={className}
        describedBy={describedBy}
        ariaLabel={ariaLabel}
      >
        {label ?? <span className="text-subtle-foreground">{placeholder}</span>}
      </Trigger>
      <Popup>{renderOptions(options)}</Popup>
    </BaseSelect.Root>
  );
}

/**
 * Options from a string enum, in declaration order.
 *
 * The console has many `XValues` arrays generated from the API's enums; this
 * turns one into options without a `.map` at every call site. `humanise` is
 * applied unless a label is supplied, so `UNDER_REVIEW` reads as "Under
 * review" rather than being retyped in twenty places.
 */
export function optionsFromValues<T extends string>(
  values: readonly T[],
  label?: (value: T) => string,
): SelectOption<T>[] {
  return values.map((value) => ({
    value,
    label: label ? label(value) : defaultLabel(value),
  }));
}

function defaultLabel(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim();
  if (spaced === spaced.toUpperCase()) {
    return spaced.charAt(0) + spaced.slice(1).toLowerCase();
  }
  return spaced;
}
