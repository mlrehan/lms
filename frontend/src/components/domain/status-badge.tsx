"use client";

import type { ReactNode } from "react";
import { Badge, type BadgeTone } from "@/components/ui/primitives";
import { humanise } from "@/lib/utils";

/**
 * The colour a status gets, in one place.
 *
 * Every one of these enums comes from the backend, so the maps are keyed by
 * the API's own values. A value that is not listed falls back to neutral and
 * still displays -- the alternative, an unstyled blank, hides a state that
 * exists rather than admitting the console has not been taught about it.
 */

const USER: Record<string, BadgeTone> = {
  ACTIVE: "success",
  INACTIVE: "neutral",
  SUSPENDED: "warning",
  DELETED: "danger",
};

const COURSE: Record<string, BadgeTone> = {
  DRAFT: "neutral",
  PUBLISHED: "info",
  RUNNING: "success",
  COMPLETED: "primary",
  ARCHIVED: "neutral",
};

const ENROLLMENT: Record<string, BadgeTone> = {
  PENDING: "warning",
  CONFIRMED: "success",
  COMPLETED: "primary",
  DROPPED: "neutral",
  CANCELLED: "danger",
};

const ATTENDANCE: Record<string, BadgeTone> = {
  PRESENT: "success",
  LATE: "warning",
  ABSENT: "danger",
  EXCUSED: "info",
};

const DELIVERY: Record<string, BadgeTone> = {
  queued: "neutral",
  delivered: "success",
  failed: "danger",
  retrying: "warning",
  abandoned: "danger",
};

const MEMBERSHIP: Record<string, BadgeTone> = {
  ACTIVE: "success",
  INVITED: "info",
  SUSPENDED: "warning",
  REMOVED: "neutral",
};

const MAPS = {
  user: USER,
  course: COURSE,
  enrollment: ENROLLMENT,
  attendance: ATTENDANCE,
  delivery: DELIVERY,
  membership: MEMBERSHIP,
} as const;

export function StatusBadge({
  value,
  kind,
  className,
}: {
  value: string | null | undefined;
  kind: keyof typeof MAPS;
  className?: string;
}): ReactNode {
  if (!value) return <span className="text-muted-foreground">—</span>;
  const tone = MAPS[kind][value] ?? "neutral";
  return (
    <Badge tone={tone} className={className}>
      {humanise(value)}
    </Badge>
  );
}

export function BooleanBadge({
  value,
  trueLabel = "Yes",
  falseLabel = "No",
  trueTone = "success",
  falseTone = "neutral",
}: {
  value: boolean | null | undefined;
  trueLabel?: string;
  falseLabel?: string;
  trueTone?: BadgeTone;
  falseTone?: BadgeTone;
}): ReactNode {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  return <Badge tone={value ? trueTone : falseTone}>{value ? trueLabel : falseLabel}</Badge>;
}
