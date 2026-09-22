"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, ExternalLink, Film, Link2, MapPin, Users } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type { CalendarSession, OverviewPerson, OverviewRosterEntry, SessionOverview } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { ErrorState } from "@/components/ui/states";
import { formatTime } from "@/lib/format/datetime";
import { humanise } from "@/lib/utils";
import { JoinClassButton } from "@/components/domain/sessions/join-class-button";
import { ClassRecording } from "@/components/domain/sessions/class-recording";

const ATTENDANCE_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  PRESENT: "success",
  LATE: "warning",
  ABSENT: "danger",
  EXCUSED: "neutral",
};

function Section({ icon, title, children }: { icon?: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {icon}
        {title}
      </h4>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Person({ person, label }: { person: OverviewPerson; label?: string }) {
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
      <span className="font-medium">{person.name}</span>
      {label ? <span className="text-xs text-muted-foreground">({label})</span> : null}
      {person.email ? (
        <a href={`mailto:${person.email}`} className="text-xs text-primary hover:underline">
          {person.email}
        </a>
      ) : null}
      {person.phone ? <span className="text-xs text-muted-foreground">{person.phone}</span> : null}
    </span>
  );
}

function RosterRow({ entry }: { entry: OverviewRosterEntry }) {
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Person person={entry.student} />
        <span className="flex items-center gap-1.5">
          {entry.attendance ? <Badge tone={ATTENDANCE_TONE[entry.attendance] ?? "neutral"}>{humanise(entry.attendance)}</Badge> : null}
          <Badge tone={entry.enrollment_status === "CONFIRMED" ? "success" : "neutral"}>{humanise(entry.enrollment_status)}</Badge>
        </span>
      </div>
      {(entry.guardians ?? []).map((guardian) => (
        <p key={guardian.public_id} className="pl-3 text-xs text-muted-foreground">
          Guardian: <Person person={guardian} label={guardian.detail ?? undefined} />
        </p>
      ))}
      {(entry.managers ?? []).map((manager) => (
        <p key={manager.public_id} className="pl-3 text-xs text-muted-foreground">
          Manager{entry.organization ? ` at ${entry.organization}` : ""}: <Person person={manager} label={manager.detail ?? undefined} />
        </p>
      ))}
      {entry.organization && (entry.managers ?? []).length === 0 ? <p className="pl-3 text-xs text-muted-foreground">Employer: {entry.organization}</p> : null}
    </li>
  );
}

/**
 * The full picture of one class: what it is, who teaches it, where, and who is in it.
 *
 * What is *listed* is decided by the server from the caller's own permissions: an administrator gets the
 * whole roster with guardians and managers, a tutor their batch, a student only themselves, a guardian or
 * corporate manager only their people. This component renders whatever arrives and says when it is partial.
 */
export function SessionDetailsDialog({
  session,
  canManage,
  timeZone,
  googleUrl,
  onClose,
  onEdit,
  onDeleted,
}: {
  session: CalendarSession | null;
  canManage: boolean;
  timeZone: string;
  googleUrl: string | null;
  onClose: () => void;
  onEdit: (session: CalendarSession) => void;
  onDeleted: (session: CalendarSession) => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const id = session?.public_id;

  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["sessions", "overview", id],
    queryFn: () => api.get<SessionOverview>(`/sessions/${segment(id ?? "")}/overview`),
    enabled: Boolean(id),
  });

  const remove = useApiMutation<void, CalendarSession>({
    mutationFn: (s) => api.delete<void>(`/sessions/${segment(s.public_id)}`),
    success: "Session deleted.",
    onSuccess: (_data, s) => {
      setConfirm(false);
      onDeleted(s);
    },
  });

  const when = session
    ? `${new Intl.DateTimeFormat("en-GB", { dateStyle: "full", timeStyle: "short", timeZone }).format(new Date(session.session_start_time))} – ${formatTime(session.session_end_time, { timeZone })}`
    : "";
  const counts = data?.attendance_counts ?? {};

  return (
    <>
      <Dialog open={session !== null} onOpenChange={(next) => !next && onClose()}>
        <DialogContent size="lg">
          {session ? (
            <>
              <DialogHeader
                title={session.course_title ?? session.batch_code}
                description={`${data ? `Session ${data.number} of ${data.total} · ` : ""}${session.batch_code} · ${when}`}
              />
              <div className="space-y-5">
                <Section icon={<CalendarDays className="size-3.5" aria-hidden />} title="Session">
                  <dl className="divide-y divide-border-subtle rounded-lg border border-border-subtle px-3">
                    <Row label="Course">
                      {data ? (
                        <>
                          {data.course.title}
                          {data.course.code ? <span className="text-muted-foreground"> ({data.course.code})</span> : null}
                          {data.course.level ? <span className="text-muted-foreground"> · {humanise(data.course.level)}</span> : null}
                        </>
                      ) : (
                        session.course_title
                      )}
                    </Row>
                    <Row label="Batch">
                      <Link href={`/batches/${session.batch_id}`} className="font-mono text-primary hover:underline">
                        {session.batch_code}
                      </Link>
                      {data ? (
                        <span className="text-muted-foreground">
                          {" "}
                          · {data.batch.enrolled ?? 0}
                          {data.batch.capacity ? ` of ${data.batch.capacity}` : ""} enrolled{data.batch.is_active ? "" : " · closed"}
                        </span>
                      ) : null}
                    </Row>
                    <Row label="Tutor">{data ? <Person person={data.tutor} /> : session.tutor_name}</Row>
                    <Row label="Duration">{data?.duration_minutes ? `${data.duration_minutes} minutes` : "—"}</Row>
                  </dl>
                </Section>

                <Section icon={<MapPin className="size-3.5" aria-hidden />} title="Where">
                  <dl className="divide-y divide-border-subtle rounded-lg border border-border-subtle px-3">
                    <Row label="Platform">
                      {humanise(session.platform)}
                      {session.classroom ? ` · ${session.classroom}` : ""}
                    </Row>
                    {/* The raw link is only in `data` for staff; everyone else
                        gets the button, which asks the API for it inside the
                        join window and nowhere else. */}
                    <Row label="Join">
                      <JoinClassButton
                        sessionId={session.public_id}
                        canJoinNow={data?.can_join_now ?? false}
                        opensAt={data?.join_opens_at}
                        closesAt={data?.join_closes_at}
                        size="xs"
                      />
                    </Row>
                    <Row label="Calendar">
                      {data?.in_google ? <Badge tone="success">In Google Calendar</Badge> : <Badge tone="neutral">Not in Google Calendar yet</Badge>}
                    </Row>
                  </dl>
                </Section>

                {/* Full width, not a Row: a 6.5rem label column beside a video
                    leaves the player squeezed into a third of the dialog. */}
                {data?.has_recording ? (
                  <Section icon={<Film className="size-3.5" aria-hidden />} title="Recording">
                    <ClassRecording sessionId={session.public_id} />
                  </Section>
                ) : null}

                {data?.student_notes || data?.tutor_notes ? (
                  <Section icon={<Link2 className="size-3.5" aria-hidden />} title="Notes">
                    <dl className="divide-y divide-border-subtle rounded-lg border border-border-subtle px-3">
                      {data.student_notes ? <Row label="For students">{data.student_notes}</Row> : null}
                      {data.tutor_notes ? <Row label="Tutor notes">{data.tutor_notes}</Row> : null}
                    </dl>
                  </Section>
                ) : null}

                <Section icon={<Users className="size-3.5" aria-hidden />} title={data ? `Students (${data.roster.length})` : "Students"}>
                  {isPending ? (
                    <p className="text-sm text-muted-foreground">Loading…</p>
                  ) : error ? (
                    <ErrorState error={error} onRetry={() => void refetch()} />
                  ) : (
                    <>
                      {Object.keys(counts).length > 0 ? (
                        <p className="flex flex-wrap gap-1.5">
                          {Object.entries(counts).map(([status, n]) => (
                            <Badge key={status} tone={ATTENDANCE_TONE[status] ?? "neutral"}>
                              {humanise(status)} {n}
                            </Badge>
                          ))}
                        </p>
                      ) : null}
                      {data.roster.length === 0 ? (
                        <p className="text-sm text-muted-foreground">Nobody is enrolled.</p>
                      ) : (
                        <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle px-3">
                          {data.roster.map((entry) => (
                            <RosterRow key={entry.student.public_id} entry={entry} />
                          ))}
                        </ul>
                      )}
                      {data.roster_is_partial ? <p className="text-xs text-muted-foreground">You see only the students you are responsible for.</p> : null}
                    </>
                  )}
                </Section>
              </div>
              <DialogFooter>
                <Link href={`/batches/${session.batch_id}`} className="mr-auto text-sm text-primary hover:underline">
                  Open batch
                </Link>
                {googleUrl ? (
                  <a href={googleUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
                    Google Calendar <ExternalLink className="size-3.5" aria-hidden />
                  </a>
                ) : null}
                {canManage ? (
                  <>
                    <Button variant="ghost" onClick={() => setConfirm(true)}>
                      Delete
                    </Button>
                    <Button onClick={() => onEdit(session)}>Edit</Button>
                  </>
                ) : (
                  <Button variant="secondary" onClick={onClose}>
                    Close
                  </Button>
                )}
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={confirm && session !== null}
        onOpenChange={setConfirm}
        destructive
        title="Delete this session?"
        description="It is removed from the timetable and from Google Calendar. If attendance was already taken, it is kept as cancelled instead."
        confirmLabel="Delete session"
        pending={remove.isPending}
        onConfirm={() => {
          if (session) remove.mutate(session);
        }}
      />
    </>
  );
}
