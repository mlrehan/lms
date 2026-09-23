"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Plus, Scale, Star } from "lucide-react";

import { api, segment } from "@/lib/api/client";
import type {
  GradeComponentType,
  GradingSchemeResponse,
  GradingSchemeSummary,
} from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

/**
 * Where an institution decides what counts and how much (spec §6, §13).
 *
 * The most consequential screen in the academic system: saving a weighting
 * re-grades every student in every course using the scheme, at once. Three
 * things follow from that, and each is visible in the UI rather than left to a
 * docstring nobody reads:
 *
 * 1. **The running total is always on screen.** A scheme that does not add to
 *    100 cannot be activated, and an operator should see how far off they are
 *    without doing the sum in their head.
 * 2. **"How many courses use this" is shown before a change**, not after.
 * 3. **Activating and making-default are separate, deliberate buttons.** Neither
 *    happens as a side effect of editing.
 */

const COMPONENTS: { value: GradeComponentType; label: string; hint: string }[] = [
  { value: "ASSIGNMENT", label: "Assignments", hint: "Graded coursework submissions." },
  { value: "QUIZ", label: "Quizzes", hint: "Best attempt per quiz." },
  { value: "FINAL_EXAM", label: "Examinations", hint: "Recorded examination marks." },
  { value: "ATTENDANCE", label: "Attendance", hint: "Read from the register; never stored twice." },
  { value: "PRACTICAL", label: "Class performance", hint: "Tutor-assigned marks per session." },
];

type WeightMap = Partial<Record<GradeComponentType, string>>;

function useSchemes() {
  return useQuery({
    queryKey: ["grading-schemes"],
    queryFn: () => api.get<GradingSchemeSummary[]>("/grading-schemes"),
  });
}

function CreateDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [name, setName] = useState("");
  const [policy, setPolicy] = useState("EXCLUDE");
  const [passing, setPassing] = useState("50");
  const [description, setDescription] = useState("");

  const create = useApiMutation<GradingSchemeResponse, void>({
    mutationFn: () =>
      api.post<GradingSchemeResponse>("/grading-schemes", {
        body: {
          name,
          description: description || null,
          missing_mark_policy: policy,
          passing_percentage: Number(passing),
        },
      }),
    success: "Scheme created. Set its weightings, then activate it.",
    invalidate: [["grading-schemes"]],
    onSuccess: () => {
      setName("");
      setDescription("");
      onOpenChange(false);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader
          title="New grading scheme"
          description="Created inactive. Nothing is graded by it until you set the weightings and activate it."
        />
        <div className="space-y-4">
          <Field label="Name" required>
            {({ id }) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Description">
            {({ id }) => (
              <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} />
            )}
          </Field>
          <FormGrid>
            <Field label="Overall pass mark (%)">
              {({ id }) => (
                <Input id={id} type="number" min={0} max={100} value={passing}
                       onChange={(e) => setPassing(e.target.value)} />
              )}
            </Field>
            <Field label="Work with no mark yet">
              {({ id }) => (
                <NativeSelect id={id} value={policy} onChange={(e) => setPolicy(e.target.value)}>
                  <option value="EXCLUDE">Leave out of the total</option>
                  <option value="ZERO">Count as zero</option>
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          {/* The choice with the widest consequences on this dialog, so it is
              explained rather than left as two words in a dropdown. */}
          <p className="rounded-lg border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
            {policy === "EXCLUDE"
              ? "An examination that has not happened yet is left out, so a student's standing is shown out of what has actually been assessed."
              : "Unassessed work scores nothing and still takes its full share of the total. Only choose this if it is genuinely your academic rule — it makes a student who has sat nothing look like one who failed everything."}
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={name.trim().length < 2}
                  onClick={() => create.mutate()}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SchemeEditor({ publicId, onClose }: { publicId: string; onClose: () => void }) {
  const { permissions } = useSession();
  const canManage = permissions.has("grading_scheme.manage");
  const [confirmDefault, setConfirmDefault] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["grading-schemes", publicId],
    queryFn: () => api.get<GradingSchemeResponse>(`/grading-schemes/${segment(publicId)}`),
  });

  const [draft, setDraft] = useState<WeightMap | null>(null);
  // Seeded from the server the first time the scheme loads, then owned by the
  // form. Re-seeding on every render would discard what the operator typed.
  const weights = useMemo<WeightMap>(() => {
    if (draft) return draft;
    const seeded: WeightMap = {};
    for (const c of data?.components ?? []) {
      seeded[c.component_type] = String(c.weight_percentage);
    }
    return seeded;
  }, [draft, data]);

  const total = useMemo(
    () =>
      Object.values(weights).reduce((sum, v) => sum + (Number(v) || 0), 0),
    [weights],
  );
  const balanced = Math.abs(total - 100) <= 0.05;

  const save = useApiMutation<GradingSchemeResponse, void>({
    mutationFn: () =>
      api.put<GradingSchemeResponse>(`/grading-schemes/${segment(publicId)}/components`, {
        body: {
          components: COMPONENTS.filter((c) => Number(weights[c.value] ?? 0) > 0).map((c) => ({
            component_type: c.value,
            weight_percentage: Number(weights[c.value]),
          })),
        },
      }),
    success: "Weightings saved.",
    invalidate: [["grading-schemes"], ["performance"], ["gradebook"]],
    onSuccess: () => setDraft(null),
  });

  const activate = useApiMutation<GradingSchemeResponse, void>({
    mutationFn: () =>
      api.post<GradingSchemeResponse>(`/grading-schemes/${segment(publicId)}/activate`, { body: {} }),
    success: "Scheme activated.",
    invalidate: [["grading-schemes"], ["performance"]],
  });

  const makeDefault = useApiMutation<GradingSchemeResponse, void>({
    mutationFn: () =>
      api.post<GradingSchemeResponse>(`/grading-schemes/${segment(publicId)}/make-default`, { body: {} }),
    success: "This is now the institution's default scheme.",
    invalidate: [["grading-schemes"], ["performance"]],
    onSuccess: () => setConfirmDefault(false),
  });

  if (isPending) return <LoadingState rows={6} />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (!data) return null;

  return (
    <Card>
      <CardHeader
        title={data.name}
        description={data.description ?? "No description."}
        actions={
          <span className="flex flex-wrap items-center gap-2">
            {data.is_default ? <Badge tone="success" dot>Institution default</Badge> : null}
            <Badge tone={data.is_active ? "success" : "warning"}>
              {data.is_active ? "Active" : "Not activated"}
            </Badge>
            <Button variant="ghost" size="sm" onClick={onClose}>
              Close
            </Button>
          </span>
        }
      />
      <CardBody className="space-y-5">
        {/* Shown before a change, not after: editing a weight re-grades every
            student in every one of these courses at once. */}
        {(data.courses_using ?? 0) > 0 ? (
          <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
            {data.courses_using} course{data.courses_using === 1 ? "" : "s"} graded by this
            scheme. Changing a weighting recalculates every student in them.
          </p>
        ) : null}

        <div className="space-y-3">
          <p className="text-sm font-medium">Weightings</p>
          {COMPONENTS.map((c) => (
            <div key={c.value} className="grid grid-cols-[1fr_7rem] items-center gap-3">
              <div className="min-w-0">
                <p className="text-sm">{c.label}</p>
                <p className="text-xs text-muted-foreground">{c.hint}</p>
              </div>
              <Input
                type="number"
                min={0}
                max={100}
                step="0.01"
                aria-label={`${c.label} weight, percent`}
                value={weights[c.value] ?? ""}
                disabled={!canManage}
                onChange={(e) => setDraft({ ...weights, [c.value]: e.target.value })}
              />
            </div>
          ))}

          {/* The running total, always visible. A scheme that does not add up
              cannot be activated, and an operator should not have to do the
              arithmetic to find that out. */}
          <div
            className={cn(
              "flex items-center justify-between rounded-lg border px-3 py-2 text-sm",
              balanced
                ? "border-success/40 bg-success/10 text-success"
                : "border-warning/40 bg-warning/10 text-warning",
            )}
          >
            <span>Total</span>
            <span className="tabular-nums font-semibold">
              {total.toFixed(2)}%
              {balanced ? null : ` — ${(100 - total).toFixed(2)}% ${total > 100 ? "over" : "short"}`}
            </span>
          </div>
        </div>

        {canManage ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button loading={save.isPending} disabled={draft === null} onClick={() => save.mutate()}>
              Save weightings
            </Button>
            {!data.is_active ? (
              <Button
                variant="secondary"
                loading={activate.isPending}
                // Disabled rather than hidden, with the total beside it saying
                // why: a button that vanishes leaves nobody knowing what to fix.
                disabled={!balanced || (data.component_count ?? 0) === 0}
                onClick={() => activate.mutate()}
              >
                <CheckCircle2 /> Activate
              </Button>
            ) : null}
            {data.is_active && !data.is_default ? (
              <Button variant="secondary" onClick={() => setConfirmDefault(true)}>
                <Star /> Make institution default
              </Button>
            ) : null}
          </div>
        ) : null}

        {(data.bands ?? []).length ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">Grade ladder</p>
            <div className="flex flex-wrap gap-2">
              {(data.bands ?? []).map((b) => (
                <Badge key={b.letter_grade} tone={b.is_pass ? "neutral" : "danger"}>
                  {b.letter_grade} · {b.min_score}–{b.max_score}% · {b.gpa_points} GPA
                </Badge>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            No grade ladder set. Results are reported as a percentage against the
            overall pass mark of {data.passing_percentage}%.
          </p>
        )}
      </CardBody>

      <ConfirmDialog
        open={confirmDefault}
        onOpenChange={setConfirmDefault}
        title="Make this the institution default?"
        description="Every course without a scheme of its own will be graded by it from now on. This changes results across the institution."
        confirmLabel="Make default"
        onConfirm={() => makeDefault.mutate()}
      />
    </Card>
  );
}

export default function GradingSchemesPage() {
  const { permissions } = useSession();
  const canManage = permissions.has("grading_scheme.manage");
  const { data, isPending, error, refetch } = useSchemes();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Grading schemes"
        description="What counts towards a result, how much each part is worth, and what the final figure is called."
        actions={
          canManage ? (
            <Button onClick={() => setCreating(true)}>
              <Plus /> New scheme
            </Button>
          ) : null
        }
      />

      {isPending ? (
        <LoadingState rows={4} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : !data?.length ? (
        <EmptyState
          icon={<Scale />}
          title="No grading schemes"
          description="A scheme decides how assignments, examinations, attendance and class performance combine into one result."
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.map((scheme) => {
            const balanced = Math.abs(Number(scheme.total_weight) - 100) <= 0.05;
            return (
              <button
                key={scheme.public_id}
                type="button"
                onClick={() => setSelected(scheme.public_id)}
                className={cn(
                  "rounded-lg border p-3 text-left transition-colors",
                  selected === scheme.public_id
                    ? "border-primary bg-primary/5"
                    : "border-border-subtle hover:bg-surface-muted",
                )}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{scheme.name}</span>
                  {scheme.is_default ? <Badge tone="success" dot>Default</Badge> : null}
                  {!scheme.is_active ? <Badge tone="warning">Not activated</Badge> : null}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {(scheme.component_count ?? 0) === 0
                    ? "No weightings set — nothing is graded by this yet."
                    : `${scheme.component_count} component(s), totalling ${Number(scheme.total_weight).toFixed(2)}%`}
                  {(scheme.component_count ?? 0) > 0 && !balanced ? " — does not add up to 100%" : ""}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {selected ? <SchemeEditor publicId={selected} onClose={() => setSelected(null)} /> : null}

      <CreateDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}
