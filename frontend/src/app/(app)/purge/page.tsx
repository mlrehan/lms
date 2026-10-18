"use client";

/**
 * Permanent deletion, and the complete system reset.
 *
 * **The design brief for this screen is "make the consequence unmissable, and
 * make the safe path the easy one".** It is the only screen in the product
 * where a mistake cannot be undone, so:
 *
 * * Nothing happens on a single click. Choosing records produces a *preview*,
 *   and the preview is what the delete button appears beneath.
 * * The preview names every record by its own title or username, so somebody
 *   can see they picked the right rows rather than trusting an id.
 * * Deletions and detachments are shown apart. "47 rows affected" would hide
 *   that 40 of them merely lose a reference.
 * * The confirmation phrase carries the real count, and is compared exactly.
 *   Typing it means having read the one figure that says how much is going.
 * * A refusal from the server is shown where the button is, not as a toast
 *   that disappears.
 *
 * **There is no second factor and no CAPTCHA here, by instruction.** The
 * screen says so plainly in `WhatProtectsThis`, rather than implying a
 * stronger gate than exists -- an operator who believes a second factor stands
 * behind this will treat the screen more casually than they should.
 */

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  Database,
  Eraser,
  Info,
  Loader2,
  RotateCcw,
  ShieldAlert,
  Trash2,
  Unlink,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Input, Textarea } from "@/components/ui/form";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Separator,
} from "@/components/ui/primitives";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Column, DataTable } from "@/components/ui/data-table";
import { useSession } from "@/lib/auth/session";
import {
  type EmptyBatchRow,
  type PurgeDependencyRow,
  type PurgePreviewResponse,
  type SystemResetResponse,
  parseIds,
  useEmptyBatches,
  usePurgeEntities,
  usePurgeExecute,
  usePurgePreview,
  useSystemResetExecute,
  useSystemResetPreview,
} from "@/lib/api/purge";
import { cn } from "@/lib/utils";

export default function PurgePage(): ReactNode {
  const { permissions } = useSession();
  const entities = usePurgeEntities();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Permanent deletion"
        description="Erase records beyond recovery, or return the whole installation to a freshly-installed state."
        breadcrumbs={[{ label: "Administration" }, { label: "Permanent deletion" }]}
      />

      <HardWarning />

      {entities.isLoading ? (
        <LoadingState />
      ) : entities.isError ? (
        <ErrorState
          error={entities.error}
          context="this screen"
          onRetry={() => void entities.refetch()}
        />
      ) : entities.data ? (
        <>
          <DeleteRecords data={entities.data} />
          <WhatIsNotDeletable blocked={entities.data.blocked} />
          {entities.data.unsupported_constraints.length > 0 ? (
            <UnsupportedConstraints names={entities.data.unsupported_constraints} />
          ) : null}
        </>
      ) : null}

      <WhatProtectsThis />

      {permissions.has("system.reset") ? <SystemReset /> : null}
    </div>
  );
}

/* ========================================================================== */
/* The warning                                                                */
/* ========================================================================== */

function HardWarning(): ReactNode {
  return (
    <div
      role="alert"
      className="rounded-lg border-2 border-danger/60 bg-danger/5 p-4 sm:p-5"
    >
      <div className="flex gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 space-y-2">
          <h2 className="text-sm font-semibold text-danger">
            Everything on this page is permanent. There is no undo, and no recycle bin.
          </h2>
          <p className="text-xs leading-relaxed text-muted-foreground">
            The rest of the product deletes records by hiding them, so a mistake can be put
            right. This page does not. A record deleted here is removed from the database,
            together with everything that depended on it — a student&apos;s enrolments,
            submissions, marks and attendance go with the student.
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            <strong className="font-medium text-foreground">
              Nothing is deleted until you have seen a preview and typed the confirmation.
            </strong>{" "}
            If you are not certain, deactivate the account or archive the course instead —
            both are reversible and both keep the record.
          </p>
        </div>
      </div>
    </div>
  );
}

function WhatProtectsThis(): ReactNode {
  return (
    <Card>
      <CardHeader title={<TitleWithIcon icon={<ShieldAlert className="size-4 text-primary" aria-hidden />}>What stands between a click and a loss</TitleWithIcon>} />
      <CardBody className="space-y-2 text-xs leading-relaxed text-muted-foreground">
        <ul className="space-y-1.5">
          <li>
            <strong className="font-medium text-foreground">Super Admin only.</strong> This
            page is refused to every other role, on the server as well as here.
          </li>
          <li>
            <strong className="font-medium text-foreground">A preview you have to read.</strong>{" "}
            The confirmation phrase contains the real number of affected records, and is
            recalculated when you confirm — so if anything changed in between, the deletion is
            refused rather than enlarged.
          </li>
          <li>
            <strong className="font-medium text-foreground">Protections that cannot be waived.</strong>{" "}
            You cannot delete your own account, the last active Super Admin, the permission
            catalogue, or the audit trail.
          </li>
          <li>
            <strong className="font-medium text-foreground">A record that outlives the records.</strong>{" "}
            Every deletion is written to the audit log, which the database keeps append-only.
          </li>
        </ul>
        <Separator />
        <p>
          There is deliberately{" "}
          <strong className="font-medium text-foreground">
            no second factor and no CAPTCHA
          </strong>{" "}
          on this page. The gate is your Super Admin session, the preview, and the typed
          confirmation. It is written here so you know exactly how much is standing in the way.
        </p>
      </CardBody>
    </Card>
  );
}

/* ========================================================================== */
/* Deleting records                                                           */
/* ========================================================================== */

function DeleteRecords({
  data,
}: {
  data: { entities: { key: string; label: string; singular: string; consequence: string }[] };
}): ReactNode {
  const [entity, setEntity] = useState<string>(data.entities[0]?.key ?? "");
  const [raw, setRaw] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [preview, setPreview] = useState<PurgePreviewResponse | null>(null);
  const [done, setDone] = useState<PurgePreviewResponse | null>(null);

  const previewMutation = usePurgePreview();
  const executeMutation = usePurgeExecute();

  const chosen = data.entities.find((e) => e.key === entity);
  const { ids, rejected } = useMemo(() => parseIds(raw), [raw]);

  /** Any change to the selection invalidates a preview that described the old one. */
  function reset(): void {
    setPreview(null);
    setConfirmation("");
    setDone(null);
    previewMutation.reset();
    executeMutation.reset();
  }

  const canConfirm =
    preview !== null &&
    preview.blockers.length === 0 &&
    preview.found > 0 &&
    confirmation.trim().toUpperCase() === preview.confirmation_phrase.toUpperCase();

  return (
    <Card>
      <CardHeader
        title={<TitleWithIcon icon={<Trash2 className="size-4 text-danger" aria-hidden />}>Delete records permanently</TitleWithIcon>}
        description="Choose what to delete, check the preview, then confirm."
       
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
          <label className="space-y-1.5">
            <span className="block text-xs font-medium">Type of record</span>
            <Select
              value={entity}
              onValueChange={(value) => {
                // The field is not clearable, so `null` cannot arrive -- but
                // the signature allows it and silently keeping the old value
                // is the safe reading on a deletion screen.
                if (value === null) return;
                setEntity(value);
                reset();
              }}
              options={data.entities.map((e) => ({
                value: e.key,
                label: e.label,
                description: `Also deletes ${e.consequence}`,
              }))}
            />
          </label>
          <label className="space-y-1.5">
            <span className="block text-xs font-medium">
              Record numbers
              <span className="ml-1.5 font-normal text-subtle-foreground">
                one per line, or separated by commas
              </span>
            </span>
            <Textarea
              value={raw}
              rows={3}
              spellCheck={false}
              placeholder={"104\n117\n238"}
              onChange={(event) => {
                setRaw(event.target.value);
                reset();
              }}
            />
          </label>
        </div>

        {chosen ? (
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0 text-subtle-foreground" aria-hidden />
            <span>
              Deleting {chosen.label.toLowerCase()} also deletes{" "}
              <strong className="font-medium text-foreground">{chosen.consequence}</strong>.
            </span>
          </p>
        ) : null}

        {entity === "batch" ? <EmptyBatchHelper onUse={(id) => { setRaw(String(id)); reset(); }} /> : null}

        {rejected.length > 0 ? (
          <p className="text-xs text-warning">
            {rejected.length === 1
              ? `"${rejected[0]}" is not a record number and was ignored.`
              : `${rejected.length} entries were not record numbers and were ignored: ${rejected
                  .slice(0, 5)
                  .map((value) => `"${value}"`)
                  .join(", ")}${rejected.length > 5 ? "…" : ""}`}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            disabled={ids.length === 0 || previewMutation.isPending}
            onClick={() => {
              setConfirmation("");
              setDone(null);
              executeMutation.reset();
              previewMutation.mutate(
                { entity, ids },
                { onSuccess: (result) => setPreview(result) },
              );
            }}
          >
            {previewMutation.isPending ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <ArrowRight className="size-3.5" aria-hidden />
            )}
            Check what this would delete
          </Button>
          {ids.length > 0 ? (
            <span className="text-xs text-muted-foreground">
              {ids.length} record {ids.length === 1 ? "number" : "numbers"} entered
            </span>
          ) : null}
        </div>

        {previewMutation.isError ? (
          <Refusal message={previewMutation.error.message} />
        ) : null}

        {done ? <Completed result={done} /> : null}

        {preview && !done ? (
          <PreviewPanel
            preview={preview}
            confirmation={confirmation}
            onConfirmationChange={setConfirmation}
            canConfirm={canConfirm}
            pending={executeMutation.isPending}
            error={executeMutation.isError ? executeMutation.error.message : null}
            onDelete={() =>
              executeMutation.mutate(
                { entity, ids, confirmation },
                {
                  onSuccess: (result) => {
                    setDone(result);
                    setPreview(null);
                    setRaw("");
                    setConfirmation("");
                  },
                },
              )
            }
          />
        ) : null}
      </CardBody>
    </Card>
  );
}

function PreviewPanel({
  preview,
  confirmation,
  onConfirmationChange,
  canConfirm,
  pending,
  error,
  onDelete,
}: {
  preview: PurgePreviewResponse;
  confirmation: string;
  onConfirmationChange: (value: string) => void;
  canConfirm: boolean;
  pending: boolean;
  error: string | null;
  onDelete: () => void;
}): ReactNode {
  const missing = preview.requested - preview.found;

  return (
    <div className="space-y-4 rounded-lg border-2 border-danger/50 bg-danger/5 p-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-danger">
          {preview.found === 0
            ? "Nothing matching was found"
            : `This will permanently delete ${preview.deleted_rows.toLocaleString()} ${
                preview.deleted_rows === 1 ? "record" : "records"
              }`}
        </h3>
        {preview.found > 0 ? (
          <p className="text-xs text-muted-foreground">
            {preview.found.toLocaleString()}{" "}
            {noun(preview.found, preview.singular, preview.label)}, plus{" "}
            {(preview.deleted_rows - preview.found).toLocaleString()} related{" "}
            {preview.deleted_rows - preview.found === 1 ? "record" : "records"} beneath{" "}
            {preview.found === 1 ? "it" : "them"}.
            {preview.detached_rows > 0
              ? ` A further ${preview.detached_rows.toLocaleString()} ${
                  preview.detached_rows === 1 ? "record keeps" : "records keep"
                } existing with a reference removed.`
              : ""}
          </p>
        ) : null}
        {missing > 0 && preview.found > 0 ? (
          <p className="text-xs text-warning">
            {missing === 1
              ? "One of the record numbers you entered does not exist and will be skipped."
              : `${missing} of the ${preview.requested} record numbers you entered do not exist and will be skipped.`}
          </p>
        ) : null}
        {preview.found === 0 ? (
          <p className="text-xs text-muted-foreground">
            {preview.requested === 1
              ? "That record number does not exist, or is not a " +
                preview.singular.toLowerCase() +
                ". Check you have the right type of record selected."
              : `None of the ${preview.requested} record numbers you entered exist as ${preview.label.toLowerCase()}. Check you have the right type of record selected.`}
          </p>
        ) : null}
        {preview.truncated ? (
          <p className="text-xs text-warning">
            These records are nested deeper than this preview follows, so the totals are a
            minimum rather than a complete count.
          </p>
        ) : null}
      </div>

      {preview.blockers.length > 0 ? (
        <div className="space-y-1.5 rounded-md border border-danger bg-surface p-3">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-danger">
            <Ban className="size-3.5" aria-hidden />
            This cannot be deleted
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {preview.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {preview.targets.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium">What you have selected</p>
          <ul className="flex flex-wrap gap-1.5">
            {preview.targets.map((target) => (
              <li key={target.id}>
                <Badge tone="neutral">
                  <span className="font-mono text-2xs text-subtle-foreground">#{target.id}</span>
                  {target.label ? <span className="ml-1.5">{target.label}</span> : null}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {preview.breakdown.length > 0 ? (
        <DependencyList
          title="Also deleted"
          icon={<Trash2 className="size-3.5" aria-hidden />}
          rows={preview.breakdown}
        />
      ) : null}

      {preview.detached_breakdown.length > 0 ? (
        <DependencyList
          title="Kept, with the link removed"
          icon={<Unlink className="size-3.5" aria-hidden />}
          rows={preview.detached_breakdown}
          muted
        />
      ) : null}

      {preview.found > 0 && preview.blockers.length === 0 ? (
        <div className="space-y-2 border-t border-danger/30 pt-3">
          <label className="space-y-1.5">
            <span className="block text-xs font-medium">
              To confirm, type:{" "}
              <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-2xs text-danger">
                {preview.confirmation_phrase}
              </code>
            </span>
            <Input
              value={confirmation}
              spellCheck={false}
              autoComplete="off"
              placeholder={preview.confirmation_phrase}
              onChange={(event) => onConfirmationChange(event.target.value)}
            />
          </label>
          {error ? <Refusal message={error} /> : null}
          <Button variant="danger" disabled={!canConfirm || pending} onClick={onDelete}>
            {pending ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Trash2 className="size-3.5" aria-hidden />
            )}
            Delete {preview.deleted_rows.toLocaleString()}{" "}
            {preview.deleted_rows === 1 ? "record" : "records"} permanently
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function DependencyList({
  title,
  icon,
  rows,
  muted = false,
}: {
  title: string;
  icon: ReactNode;
  rows: PurgeDependencyRow[];
  muted?: boolean;
}): ReactNode {
  return (
    <div className="space-y-1.5">
      <p
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium",
          muted ? "text-muted-foreground" : "text-foreground",
        )}
      >
        {icon}
        {title}
      </p>
      <ul className="space-y-0.5">
        {rows.map((row, index) => (
          <li
            key={`${row.table}-${row.column}-${index}`}
            className="flex items-baseline justify-between gap-3 text-2xs"
            style={{ paddingLeft: `${row.depth * 0.875}rem` }}
          >
            <span className="min-w-0 truncate text-muted-foreground">
              {row.depth > 0 ? (
                <span className="mr-1 text-subtle-foreground" aria-hidden>
                  &#8627;
                </span>
              ) : null}
              {humanTable(row.table)}
            </span>
            <span className="shrink-0 font-mono tabular-nums text-foreground">
              {row.rows.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Completed({ result }: { result: PurgePreviewResponse }): ReactNode {
  return (
    <div role="status" className="space-y-1.5 rounded-lg border border-success/50 bg-success/5 p-4">
      <p className="text-sm font-semibold text-success">
        {result.deleted_rows.toLocaleString()}{" "}
        {result.deleted_rows === 1 ? "record was" : "records were"} permanently deleted.
      </p>
      <p className="text-xs text-muted-foreground">
        {result.found.toLocaleString()} {noun(result.found, result.singular, result.label)} and
        everything beneath {result.found === 1 ? "it" : "them"}.
        {result.detached_rows > 0
          ? ` ${result.detached_rows.toLocaleString()} further records kept their data and lost the link.`
          : ""}{" "}
        This is recorded in the audit log.
      </p>
    </div>
  );
}

function EmptyBatchHelper({ onUse }: { onUse: (id: number) => void }): ReactNode {
  const [open, setOpen] = useState(false);
  const batches = useEmptyBatches(open);

  return (
    <div className="rounded-md border border-border-subtle bg-surface-muted/50 p-3">
      <button
        type="button"
        className="text-xs font-medium underline-offset-2 hover:underline"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide" : "Show"} batches with nobody enrolled
      </button>
      <p className="mt-1 text-2xs text-subtle-foreground">
        Batches with no enrolments and no attendance register taken — usually created by mistake
        in the timetable. Listing them is safer than searching by hand.
      </p>
      {open ? (
        batches.isLoading ? (
          <LoadingState />
        ) : batches.isError ? (
          <p className="mt-2 text-xs text-danger">{batches.error.message}</p>
        ) : batches.data && batches.data.length > 0 ? (
          <ul className="mt-2 divide-y divide-border-subtle">
            {batches.data.map((batch: EmptyBatchRow) => (
              <li key={batch.id} className="flex items-center justify-between gap-3 py-1.5">
                <span className="min-w-0 truncate text-xs">
                  <span className="font-mono text-2xs text-subtle-foreground">#{batch.id}</span>{" "}
                  {batch.batch_code ?? "(no code)"}
                  {batch.sessions > 0 ? (
                    <span className="ml-1.5 text-subtle-foreground">
                      {batch.sessions} scheduled {batch.sessions === 1 ? "session" : "sessions"}
                    </span>
                  ) : null}
                </span>
                <Button variant="ghost" size="sm" onClick={() => onUse(batch.id)}>
                  Select
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-muted-foreground">
            Every batch has somebody enrolled or a register taken. Nothing to clean up.
          </p>
        )
      ) : null}
    </div>
  );
}

function WhatIsNotDeletable({
  blocked,
}: {
  blocked: { key: string; label: string; reason: string }[];
}): ReactNode {
  if (blocked.length === 0) return null;
  return (
    <Card>
      <CardHeader
        title={<TitleWithIcon icon={<Ban className="size-4 text-muted-foreground" aria-hidden />}>What this page will not delete</TitleWithIcon>}
        description="These are refused by design, not missing."
      />
      <CardBody>
        <dl className="space-y-3">
          {blocked.map((item) => (
            <div key={item.key} className="space-y-0.5">
              <dt className="text-xs font-medium">{item.label}</dt>
              <dd className="text-xs leading-relaxed text-muted-foreground">{item.reason}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  );
}

function UnsupportedConstraints({ names }: { names: string[] }): ReactNode {
  return (
    <div role="alert" className="rounded-lg border border-warning/60 bg-warning/5 p-4">
      <p className="text-xs font-semibold text-warning">
        This installation has {names.length} relationship
        {names.length === 1 ? "" : "s"} the preview cannot follow.
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        The counts below may be incomplete. Raise this with support before deleting anything:{" "}
        <span className="font-mono text-2xs">{names.join(", ")}</span>
      </p>
    </div>
  );
}

/* ========================================================================== */
/* The system reset                                                           */
/* ========================================================================== */

function SystemReset(): ReactNode {
  const preview = useSystemResetPreview();
  const execute = useSystemResetExecute();
  const [confirmation, setConfirmation] = useState("");
  const [outcome, setOutcome] = useState<SystemResetResponse | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const impactColumns: Column<{ table: string; label: string; rows: number }>[] = [
    { key: "label", header: "Records", cell: (row) => row.label },
    {
      key: "rows",
      header: "Count",
      cell: (row) => <span className="font-mono tabular-nums">{row.rows.toLocaleString()}</span>,
      align: "right",
    },
  ];

  if (outcome) return <ResetCompleted outcome={outcome} />;

  const blocked = !preview.data?.enabled || (preview.data?.blockers.length ?? 0) > 0;
  const phraseMatches =
    preview.data != null && confirmation.trim() === preview.data.confirmation_phrase;

  return (
    <Card className="border-danger/40">
      <CardHeader
        title={<TitleWithIcon icon={<RotateCcw className="size-4 text-danger" aria-hidden />}>Reset the whole installation</TitleWithIcon>}
        description="Erase every record and return the system to a freshly-installed state."
      />
      <CardBody className="space-y-4">
        {preview.isLoading ? (
          <LoadingState />
        ) : preview.isError ? (
          <ErrorState
            error={preview.error}
            context="the reset status"
            onRetry={() => void preview.refetch()}
          />
        ) : preview.data ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={blocked ? "neutral" : "danger"}>
                {blocked ? "Not available on this installation" : "Available — read carefully"}
              </Badge>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Database className="size-3.5" aria-hidden />
                <span className="font-mono text-2xs">{preview.data.database}</span>
                <span className="text-subtle-foreground">({preview.data.environment})</span>
              </span>
            </div>

            {preview.data.blockers.length > 0 ? (
              <div className="space-y-1.5 rounded-md border border-border-strong bg-surface-muted/60 p-3">
                <p className="text-xs font-semibold">Why a reset will not run here</p>
                <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
                  {preview.data.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-1.5">
                <p className="text-xs font-medium">
                  What a reset would erase —{" "}
                  <span className="text-danger">
                    {preview.data.total_rows.toLocaleString()} records
                  </span>
                </p>
                <DataTable
                  columns={impactColumns}
                  rows={preview.data.impact.filter((row) => row.rows > 0).slice(0, 12)}
                  rowKey={(row) => row.table}
                />
                {preview.data.impact.filter((row) => row.rows > 0).length > 12 ? (
                  <p className="text-2xs text-subtle-foreground">
                    and {preview.data.impact.filter((row) => row.rows > 0).length - 12} more kinds
                    of record
                  </p>
                ) : null}
              </div>
              <div className="space-y-1.5">
                <p className="text-xs font-medium">What it would keep</p>
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {preview.data.preserved.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <p className="pt-2 text-2xs leading-relaxed text-subtle-foreground">
                  Everyone is signed out, and one Super Admin account is left with a new password
                  shown once, on this screen. If you lose it, the only way back in is from the
                  server itself.
                </p>
              </div>
            </div>

            {!blocked ? (
              <div className="space-y-3 rounded-lg border-2 border-danger bg-danger/5 p-4">
                <p className="flex items-start gap-2 text-xs font-semibold text-danger">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>
                    This erases {preview.data.total_rows.toLocaleString()} records from{" "}
                    {preview.data.database}. It cannot be undone, and the only copy of this data
                    afterwards is your backup.
                  </span>
                </p>
                <label className="flex items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(event) => setAcknowledged(event.target.checked)}
                    className="mt-0.5 size-3.5 accent-[var(--color-danger)]"
                  />
                  <span className="text-muted-foreground">
                    I have a backup I have tested, and I understand this installation will be
                    empty afterwards.
                  </span>
                </label>
                <label className="space-y-1.5">
                  <span className="block text-xs font-medium">
                    Type{" "}
                    <code className="rounded bg-surface px-1.5 py-0.5 font-mono text-2xs text-danger">
                      {preview.data.confirmation_phrase}
                    </code>
                  </span>
                  <Input
                    value={confirmation}
                    spellCheck={false}
                    autoComplete="off"
                    onChange={(event) => setConfirmation(event.target.value)}
                  />
                </label>
                {execute.isError ? <Refusal message={execute.error.message} /> : null}
                <Button
                  variant="danger"
                  disabled={!acknowledged || !phraseMatches || execute.isPending}
                  onClick={() =>
                    execute.mutate(
                      { confirmation },
                      { onSuccess: (result) => setOutcome(result) },
                    )
                  }
                >
                  {execute.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" aria-hidden />
                  ) : (
                    <Eraser className="size-3.5" aria-hidden />
                  )}
                  Reset {preview.data.database}
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}

function ResetCompleted({ outcome }: { outcome: SystemResetResponse }): ReactNode {
  return (
    <Card className="border-success/50">
      <CardHeader title={<TitleWithIcon icon={<RotateCcw className="size-4 text-success" aria-hidden />}>The installation has been reset</TitleWithIcon>} />
      <CardBody className="space-y-4">
        <p className="text-xs text-muted-foreground">
          {outcome.rows_deleted.toLocaleString()} records were erased from{" "}
          <span className="font-mono text-2xs">{outcome.database}</span>, and{" "}
          {outcome.sessions_invalidated.toLocaleString()} sign-in sessions were ended.
        </p>

        <div className="space-y-2 rounded-lg border-2 border-warning bg-warning/5 p-4">
          <p className="text-xs font-semibold text-warning">
            Save these credentials now. They are shown once and cannot be recovered.
          </p>
          <dl className="grid gap-2 sm:grid-cols-2">
            <div>
              <dt className="text-2xs text-subtle-foreground">Username</dt>
              <dd className="font-mono text-sm">{outcome.bootstrap_username}</dd>
            </div>
            <div>
              <dt className="text-2xs text-subtle-foreground">New password</dt>
              <dd className="font-mono text-sm select-all">{outcome.bootstrap_password}</dd>
            </div>
          </dl>
          <p className="text-2xs text-muted-foreground">
            Your previous password no longer works. Sign in with this one and change it.
          </p>
        </div>

        {outcome.warnings.length > 0 ? (
          <div className="space-y-1.5">
            <p className="text-xs font-medium">Things the reset did not do</p>
            <ul className="space-y-1 text-xs leading-relaxed text-muted-foreground">
              {outcome.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/* ========================================================================== */

/** The singular when there is one of something, the plural otherwise. */
function noun(count: number, singular: string, plural: string): string {
  return (count === 1 ? singular : plural).toLowerCase();
}

/** `CardHeader.title` is a ReactNode, so an icon belongs in it rather than
 *  as a prop. It is decorative -- the heading text carries the meaning. */
function TitleWithIcon({ icon, children }: { icon: ReactNode; children: ReactNode }): ReactNode {
  return (
    <span className="flex items-center gap-2">
      {icon}
      {children}
    </span>
  );
}

function Refusal({ message }: { message: string }): ReactNode {
  return (
    <p role="alert" className="rounded-md border border-danger/60 bg-surface px-3 py-2 text-xs text-danger">
      {message}
    </p>
  );
}

/** Table names are what the server reports; these are what people call them. */
const TABLE_LABELS: Record<string, string> = {
  users: "People",
  courses: "Courses",
  batches: "Batches",
  assignments: "Assignments",
  quizzes: "Quizzes",
  exams: "Examinations",
  questions: "Quiz questions",
  question_options: "Answer options",
  resources: "Resources",
  announcements: "Announcements",
  notifications: "Notifications",
  organizations: "Organisations",
  transcripts: "Transcripts",
  grading_schemes: "Grading schemes",
  certificates: "Certificates",
  badges: "Badges",
  shared_links: "Share links",
  departments: "Departments",
  semesters: "Semesters",
  academic_years: "Academic years",
  user_roles: "Role assignments",
  enrollments: "Enrolments",
  attendances: "Attendance records",
  attendance_sheets: "Attendance registers",
  assignment_submissions: "Assignment submissions",
  assignment_submission_files: "Submission files",
  quiz_attempts: "Quiz attempts",
  quiz_answers: "Quiz answers",
  exam_results: "Exam results",
  exam_invigilators: "Invigilator assignments",
  gradebook_entries: "Grade book entries",
  class_performance_marks: "Participation marks",
  certificates_issued: "Issued certificates",
  batch_sessions: "Class sessions",
  announcement_reads: "Announcement reads",
  course_discussions: "Discussions",
  discussion_replies: "Discussion replies",
  mail_messages: "Messages",
  mail_recipients: "Message recipients",
  mail_attachments: "Message attachments",
  notification_preferences: "Notification preferences",
  push_subscriptions: "Push subscriptions",
  tokens: "Sign-in sessions",
  student_guardians: "Guardian links",
  organization_managers: "Manager appointments",
  manager_students: "Manager assignments",
  organization_memberships: "Organisation memberships",
  resource_permissions: "Resource permissions",
  resource_versions: "Resource versions",
  shared_resources: "Shared resources",
  tutor_courses: "Tutor assignments",
  tutor_reviews: "Tutor reviews",
  user_badges: "Badges awarded",
  calendar_feeds: "Calendar feeds",
  google_connections: "Google connections",
  grading_scheme_components: "Grading scheme components",
  grade_bands: "Grade bands",
};

function humanTable(table: string): string {
  return TABLE_LABELS[table] ?? table.replace(/_/g, " ");
}
