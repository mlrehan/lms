"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Pencil } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { CourseResponse } from "@/lib/api/types";
import { Badge } from "@/components/ui/primitives";
import { Dialog, DialogContent, DialogHeader } from "@/components/ui/dialog";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { CourseThumb, imageSrc } from "@/components/domain/course-image";
import { gbp } from "@/components/domain/course-form";
import { buttonVariants } from "@/components/ui/button";
import { useSession } from "@/lib/auth/session";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatCalendarDate, formatDateTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? <span className="text-muted-foreground">—</span>}</dd>
    </div>
  );
}

/** Everything the system holds about one course, in one place, without leaving the list. */
export function CourseDetailsDialog({
  courseId,
  onOpenChange,
}: {
  courseId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { permissions } = useSession();
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["courses", "detail", courseId],
    queryFn: () => api.get<CourseResponse>(`/courses/${segment(courseId ?? "")}`),
    enabled: Boolean(courseId),
  });

  return (
    <Dialog open={Boolean(courseId)} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        <DialogHeader title={data?.title ?? "Course details"} description={data?.code ? `Code ${data.code}` : undefined} />
        {isPending ? (
          <LoadingState rows={6} />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : data ? (
          <div className="space-y-5">
            <div className="flex flex-wrap items-start gap-4">
              {imageSrc(data.course_image) ? (
                // eslint-disable-next-line @next/next/no-img-element -- external or authenticated image
                <img
                  src={imageSrc(data.course_image) ?? undefined}
                  alt=""
                  className="max-h-40 max-w-full rounded-lg border border-border-subtle bg-surface object-contain"
                />
              ) : (
                <CourseThumb src={data.small_course_image} title={data.title} size="lg" />
              )}
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge value={data.status} kind="course" />
                <Badge tone="neutral">{humanise(data.level)}</Badge>
                {data.category_name ? <Badge tone="primary">{data.category_name}</Badge> : null}
                {data.department_name ? <Badge tone="neutral">{data.department_name}</Badge> : null}
                {(data.tags ?? []).map((tag) => (
                  <Badge key={tag}>#{tag}</Badge>
                ))}
              </div>
            </div>

            <dl className="divide-y divide-border-subtle rounded-lg border border-border-subtle px-4">
              <Row label="Price">{data.price != null ? gbp.format(data.price) : null}</Row>
              <Row label="Duration">{data.duration_hours != null ? `${data.duration_hours} hours` : null}</Row>
              <Row label="Course link">
                {data.course_link ? (
                  <a href={data.course_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
                    {data.course_link} <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                ) : null}
              </Row>
              <Row label="Tutors">{(data.tutors ?? []).length ? (data.tutors ?? []).join(", ") : null}</Row>
              <Row label="Batches">{data.batch_count ?? 0}</Row>
              <Row label="Created">{formatDateTime(data.created_at, { timeZone })}</Row>
              <Row label="Last updated">{data.updated_at ? formatDateTime(data.updated_at, { timeZone }) : null}</Row>
            </dl>

            <section>
              <h3 className="mb-1 text-sm font-semibold">Description</h3>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">{data.description || "No description."}</p>
            </section>
            <section>
              <h3 className="mb-1 text-sm font-semibold">Prerequisites</h3>
              <p className="whitespace-pre-wrap text-sm text-muted-foreground">{data.prerequisites || "None stated."}</p>
            </section>

            <section>
              <h3 className="mb-2 text-sm font-semibold">Batches</h3>
              {(data.batches ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No batches yet.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border-subtle">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-muted text-left">
                      <tr>
                        <th className="eyebrow px-3 py-2 text-left">Batch</th>
                        <th className="eyebrow px-3 py-2 text-left">Starts</th>
                        <th className="eyebrow px-3 py-2 text-left">Ends</th>
                        <th className="eyebrow px-3 py-2 text-right">Enrolled</th>
                        <th className="eyebrow px-3 py-2 text-left">State</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {(data.batches ?? []).map((batch) => (
                        <tr key={batch.public_id}>
                          <td className="px-3 py-1.5 font-mono text-2xs">
                            <Link href={`/batches/${batch.public_id}`} className="hover:underline">
                              {batch.batch_code}
                            </Link>
                          </td>
                          <td className="px-3 py-1.5 tabular-nums">{formatCalendarDate(batch.start_date)}</td>
                          <td className="px-3 py-1.5 tabular-nums">{formatCalendarDate(batch.end_date)}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">
                            {batch.total_enrollments ?? 0}
                            {batch.capacity ? ` / ${batch.capacity}` : ""}
                          </td>
                          <td className="px-3 py-1.5">{batch.is_active ? <Badge tone="success">Active</Badge> : <Badge>Closed</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <div className="flex justify-end gap-2">
              <Link href={`/courses/${data.public_id}`} className={buttonVariants({ variant: "secondary" })}>
                {permissions.has("course.update") ? (
                  <>
                    <Pencil /> Open and edit
                  </>
                ) : (
                  "Open course page"
                )}
              </Link>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
