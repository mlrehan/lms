"use client";

import { useId, useMemo } from "react";
import { describeTimeZone, isValidTimeZone } from "@/lib/format/datetime";
import { Input } from "@/components/ui/form";

/** Every IANA zone the browser knows. */
function allZones(): string[] {
  try {
    const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
    return supported ? supported("timeZone") : [];
  } catch {
    return [];
  }
}

/**
 * A time zone chosen by typing: the browser's own list filters as you type (`Asia/Dhaka`, `dhaka`, `london`), and
 * only a real zone is passed on, so a half-typed name never reaches a request.
 */
export function TimeZoneField({ value, onChange, id, disabled }: { value: string; onChange: (zone: string) => void; id?: string; disabled?: boolean }) {
  const list = useId();
  const zones = useMemo(() => allZones(), []);
  return (
    <>
      <Input
        id={id}
        list={list}
        defaultValue={value}
        key={value} // a zone chosen elsewhere replaces what is typed
        disabled={disabled}
        aria-invalid={!isValidTimeZone(value)}
        placeholder="e.g. Asia/Dhaka"
        onChange={(event) => {
          const next = event.target.value.trim();
          if (isValidTimeZone(next)) onChange(next);
        }}
      />
      <datalist id={list}>
        {zones.map((zone) => (
          <option key={zone} value={zone}>
            {describeTimeZone(zone)}
          </option>
        ))}
      </datalist>
    </>
  );
}
