"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "@/lib/api/client";
import type { DirectoryResponse, MailPerson } from "@/lib/api/types";
import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * A Gmail-style recipient box: chips for the people already chosen, and a search that offers only people the
 * server says you may write to. Each suggestion is a name and a role, never an email address -- the directory
 * does not have one to give.
 */
export function RecipientField({
  label,
  value,
  onChange,
  exclude = [],
  autoFocus,
}: {
  label: string;
  value: MailPerson[];
  onChange: (next: MailPerson[]) => void;
  /** People already chosen in another field of the same message, so the same person is not offered twice. */
  exclude?: MailPerson[];
  autoFocus?: boolean;
}) {
  const [term, setTerm] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(term.trim()), 200);
    return () => window.clearTimeout(id);
  }, [term]);

  const { data, isFetching } = useQuery({
    queryKey: ["mail", "recipients", debounced],
    queryFn: () => api.get<DirectoryResponse>("/messages/recipients", { query: { query: debounced || undefined, limit: 12 } }),
    enabled: open,
    staleTime: 30_000,
  });

  const taken = new Set([...value, ...exclude].map((p) => p.public_id));
  const options = (data?.items ?? []).filter((p) => !taken.has(p.public_id));

  function add(person: MailPerson) {
    onChange([...value, person]);
    setTerm("");
    setActive(0);
    inputRef.current?.focus();
  }

  return (
    <div className="relative flex items-start gap-2 border-b border-border-subtle px-3 py-1.5 text-sm">
      <span className="w-9 shrink-0 pt-1.5 text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1" onClick={() => inputRef.current?.focus()}>
        {value.map((person) => (
          <span key={person.public_id} className="inline-flex max-w-full items-center gap-1 rounded-full bg-muted py-0.5 pl-2.5 pr-1 text-xs">
            <span className="truncate">{person.name}</span>
            <button
              type="button"
              aria-label={`Remove ${person.name}`}
              className="rounded-full p-0.5 hover:bg-border"
              onClick={(event) => {
                event.stopPropagation();
                onChange(value.filter((p) => p.public_id !== person.public_id));
              }}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={term}
          autoFocus={autoFocus}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label={`${label} recipients`}
          placeholder={value.length === 0 ? "Search by name" : ""}
          className="min-w-24 flex-1 bg-transparent py-1 outline-none"
          onChange={(event) => {
            setTerm(event.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((i) => Math.min(i + 1, Math.max(options.length - 1, 0)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((i) => Math.max(i - 1, 0));
            } else if (event.key === "Enter" || event.key === ",") {
              if (options[active]) {
                event.preventDefault();
                add(options[active]);
              }
            } else if (event.key === "Backspace" && term === "" && value.length > 0) {
              onChange(value.slice(0, -1));
            } else if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
      </div>

      {open ? (
        <ul id={listId} role="listbox" className="absolute left-12 right-3 top-full z-20 mt-0.5 max-h-60 overflow-y-auto rounded-lg border border-border-subtle bg-overlay py-1 shadow-overlay">
          {options.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted-foreground">{isFetching ? "Searching…" : debounced ? "Nobody you can write to matches." : "Start typing a name."}</li>
          ) : (
            options.map((person, index) => (
              <li key={person.public_id} role="option" aria-selected={index === active}>
                <button
                  type="button"
                  className={cn("flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted", index === active && "bg-muted")}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => add(person)}
                >
                  <span className="truncate">{person.name}</span>
                  {person.role ? <Badge tone="neutral">{person.role}</Badge> : null}
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
