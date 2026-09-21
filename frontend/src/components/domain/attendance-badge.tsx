import { Badge } from "@/components/ui/primitives";

/** Attendance as a coloured percentage: 90+ good, 75+ watch, below that a problem. A dash when nothing is recorded. */
export function AttendanceBadge({ rate }: { rate: number | null | undefined }) {
  if (rate === null || rate === undefined) return <span className="text-muted-foreground">—</span>;
  return <Badge tone={rate >= 90 ? "success" : rate >= 75 ? "warning" : "danger"}>{rate.toFixed(0)}%</Badge>;
}
