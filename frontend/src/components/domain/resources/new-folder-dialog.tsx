"use client";

import { useState } from "react";
import { FolderPlus } from "lucide-react";
import { api } from "@/lib/api/client";
import type { FolderResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";
import { BatchPicker, CoursePicker } from "@/components/domain/entity-pickers";

/**
 * Creating a folder.
 *
 * **A folder at the root has to say where it belongs, and this dialog now asks.**
 * The API refuses `{name, parent_id: null}` with *"a root folder must specify
 * course_id, batch_id, or both"*, and the previous dialog collected only a name —
 * so every attempt to create a top-level folder failed with a generic "The
 * request could not be completed", and the feature was unusable from the console
 * while looking perfectly functional. That rule is right and is not worked
 * around here: a folder anchored to nothing would be visible to nobody except an
 * unrestricted administrator, so the fix is to collect the anchor rather than to
 * drop the constraint.
 *
 * **A folder inside another inherits its anchor**, so the pickers disappear once
 * there is a parent — asking again would invite an answer that contradicts the
 * parent, and the server ignores it anyway.
 */
export function NewFolderDialog({
  open,
  onOpenChange,
  parentId,
  parentName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null at the root, where an anchor is required. */
  parentId: string | null;
  parentName: string;
}) {
  const [name, setName] = useState("");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");

  const atRoot = parentId === null;

  // Not narrowed by the chosen course: `/batches` has no `course_id` filter
  // and `BatchSummary` carries only `course_title`, so narrowing would mean
  // matching on a display string. Each option names its course instead, which
  // is honest and needs no such match.
  const create = useApiMutation<FolderResponse, void>({
    mutationFn: () =>
      api.post<FolderResponse>("/folders", {
        body: {
          name: name.trim(),
          parent_id: parentId,
          // Only sent at the root. A child inherits, and sending a
          // contradicting anchor would be a request the server has to ignore.
          course_id: atRoot ? courseId || null : null,
          batch_id: atRoot ? batchId || null : null,
        },
      }),
    success: "Folder created.",
    invalidate: [["folders"]],
    onSuccess: () => {
      setName("");
      setCourseId("");
      setBatchId("");
      onOpenChange(false);
    },
  });

  // Mirrors the server's own rule so the button is disabled rather than the
  // request refused -- but the server is still the authority; this only avoids
  // sending one that cannot succeed.
  const anchored = !atRoot || courseId !== "" || batchId !== "";
  const ready = name.trim() !== "" && anchored;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title="New folder"
          description={
            atRoot
              ? "A top-level folder belongs to a course or a batch — that is what decides who can see what is inside it."
              : `Inside ${parentName}. It inherits that folder's course and batch.`
          }
        />
        <div className="space-y-4">
          <Field label="Name" required>
            {({ id }) => (
              <Input
                id={id}
                value={name}
                autoFocus
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && ready && !create.isPending) create.mutate();
                }}
              />
            )}
          </Field>

          {atRoot ? (
            <>
              <Field
                label="Course"
                hint="Everyone on the course can reach folders anchored to it."
              >
                {({ id }) => (
                  <CoursePicker id={id} value={(courseId) || null} onValueChange={(next) => setCourseId((next ?? ""))} placeholder="No course" clearable />
                )}
              </Field>

              <Field
                label="Batch"
                hint="Narrower than a course: only this batch's students reach it."
              >
                {({ id }) => (
                  <BatchPicker id={id} value={(batchId) || null} onValueChange={(next) => setBatchId((next ?? ""))} placeholder="No batch" clearable />
                )}
              </Field>

              {!anchored ? (
                <p className="text-xs text-muted-foreground">
                  Choose a course, a batch, or both. A folder attached to neither
                  would be invisible to everyone except an administrator.
                </p>
              ) : null}
            </>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={create.isPending} disabled={!ready} onClick={() => create.mutate()}>
            <FolderPlus /> Create folder
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
