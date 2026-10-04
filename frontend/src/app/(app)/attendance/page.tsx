"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { Card, Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";

import { LoadingState } from "@/components/ui/states";
import { AttendanceRecords } from "@/components/domain/attendance/records-view";
import { AttendanceSheetPanel } from "@/components/domain/attendance/sheet-panel";
import { SessionQueue, type Range, type StateFilter } from "@/components/domain/attendance/session-queue";
import { UserPicker } from "@/components/domain/user-picker";
import { api } from "@/lib/api/client";
import type { PageBatchSummary } from "@/lib/api/types";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

const STATES: { value: StateFilter; label: string }[] = [
  { value: "PENDING", label: "To do" },
  { value: "DRAFT", label: "Drafts" },
  { value: "FINALIZED", label: "Done" },
  { value: "", label: "All" },
];

/**
 * Attendance, as the work it is: **Batch -> Session -> (Tutor) -> Attendance**.
 *
 * A tutor lands on the sessions assigned to them that still need doing; the Super Admin, who can also take a
 * register on behalf of a tutor, can narrow by batch and by tutor first. People who cannot take attendance
 * (students, guardians, managers) see the records that concern them instead.
 */
function AttendanceWorkspace() {
  const params = useSearchParams();
  const { permissions } = useSession();
  const canTake = permissions.has("attendance.create");

  const [batchId, setBatchId] = useState(params.get("batch") ?? "");
  const [tutorId, setTutorId] = useState("");
  const [range, setRange] = useState<Range>("week");
  const [state, setState] = useState<StateFilter>("PENDING");
  const [sessionId, setSessionId] = useState<string | null>(params.get("session"));

  const batches = useQuery({
    queryKey: ["batches", "picker"],
    queryFn: () => api.get<PageBatchSummary>("/batches", { query: { limit: 100, sort: "batch_code" } }),
    enabled: canTake,
    staleTime: 60_000,
  });

  if (!canTake) {
    return (
      <div className="space-y-5">
        <PageHeader title="Attendance" description="The registers that concern you." />
        <AttendanceRecords />
      </div>
    );
  }

  // Choosing a tutor is for people who can see other tutors' sessions; a tutor only has their own, so it is pointless to them.
  const canPickTutor = permissions.has("attendance.override") || permissions.has("institution.view_all");

  return (
    <div className="space-y-4">
      <PageHeader title="Attendance" description="Pick a session and mark who was there. Drafts save themselves; submitting makes it the record." />

      <Tabs defaultValue="take">
        <TabsList>
          <TabsTab value="take">Take attendance</TabsTab>
          <TabsTab value="records">Records</TabsTab>
        </TabsList>

        <TabsPanel value="take">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
            <Card className={cn("flex min-h-[28rem] flex-col overflow-hidden lg:max-h-[calc(100dvh-14rem)]", sessionId && "hidden lg:flex")}>
              <div className="space-y-2 border-b border-border-subtle p-3">
                <div className="grid grid-cols-2 gap-2">
                  <Select className="h-8 text-[13px]" aria-label="Batch" value={(batchId) || null} onValueChange={(next) => setBatchId((next ?? ""))} placeholder="All batches" clearable options={(batches.data?.items ?? []).map((b) => ({ value: b.public_id, label: b.batch_code }))} />
                  <Select className="h-8 text-[13px]" aria-label="Period" value={range} onValueChange={(next) => setRange((next ?? "") as Range)} options={[{ value: "today", label: "Today" }, { value: "week", label: "Last 7 days" }, { value: "month", label: "Last 30 days" }, { value: "all", label: "Any time" }]} />
                </div>
                {canPickTutor ? <UserPicker role="TUTOR" value={tutorId || null} onChange={(id) => setTutorId(id ?? "")} placeholder="Any tutor" /> : null}
                <div role="group" aria-label="Show" className="flex gap-1">
                  {STATES.map((s) => (
                    <button
                      key={s.label}
                      type="button"
                      aria-pressed={state === s.value}
                      onClick={() => setState(s.value)}
                      className={cn("flex-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors", state === s.value ? "border-primary bg-primary/10 text-primary" : "border-border-subtle hover:bg-muted")}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <SessionQueue batchId={batchId} tutorId={tutorId} range={range} state={state} selectedId={sessionId} onSelect={(item) => setSessionId(item.session_id)} />
              </div>
            </Card>

            <section aria-label="Attendance sheet" className={cn("min-w-0", !sessionId && "hidden lg:block")}>
              {sessionId ? (
                <AttendanceSheetPanel key={sessionId} sessionId={sessionId} onBack={() => setSessionId(null)} />
              ) : (
                <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-border-subtle p-8 text-center text-sm text-muted-foreground">
                  Choose a session on the left to take its attendance.
                </div>
              )}
            </section>
          </div>
        </TabsPanel>

        <TabsPanel value="records">
          <AttendanceRecords />
        </TabsPanel>
      </Tabs>
    </div>
  );
}

export default function AttendancePage() {
  // `useSearchParams` needs a Suspense boundary in the App Router.
  return (
    <Suspense fallback={<LoadingState />}>
      <AttendanceWorkspace />
    </Suspense>
  );
}
