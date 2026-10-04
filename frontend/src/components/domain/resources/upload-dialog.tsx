"use client";

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { api } from "@/lib/api/client";
import type { ResourceResponse } from "@/lib/api/types";
import { ResourceTypeValues } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { formatBytes } from "@/components/domain/resources/drive-view";
import { BatchPicker, CoursePicker } from "@/components/domain/entity-pickers";

/**
 * Uploading files.
 *
 * **At the root, this asks which course or batch the file belongs to.** The API
 * refuses an upload that belongs to no folder, no course and no batch — *"A
 * resource must belong to a folder, a course, or a batch"* — because a file
 * anchored to nothing is reachable by nobody. The dialog used to collect only
 * the file, its name and its type, so uploading anywhere except inside a folder
 * failed; the same gap the New folder dialog had, on the other write path.
 *
 * **Inside a folder the pickers disappear**: the file inherits the folder's
 * course and batch, and asking again would invite an answer the server ignores.
 *
 * Several files upload one request each, **sequentially** — the API takes one
 * file per call, and a dropped folder of forty should not open forty
 * connections at once.
 */
export function UploadDialog({
  open,
  onOpenChange,
  folderId,
  folderName,
  initialFiles,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  folderId: string | null;
  folderName: string;
  /** Files already chosen, e.g. dropped onto the library. */
  initialFiles?: File[];
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [resourceType, setResourceType] = useState<string>("Document");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");

  const atRoot = folderId === null;

  // Adopt dropped files during render rather than in an effect, so the dialog
  // never paints once without them.
  const [seed, setSeed] = useState<File[] | undefined>(initialFiles);
  if (seed !== initialFiles) {
    setSeed(initialFiles);
    setFiles(initialFiles ?? []);
    setName(initialFiles?.length === 1 ? (initialFiles[0]?.name ?? "") : "");
  }

  const upload = useApiMutation<number, void>({
    mutationFn: async () => {
      for (const file of files) {
        const form = new FormData();
        // Appended as-is. The BFF proxy forwards the body as bytes, never as
        // decoded text -- decoding multipart as UTF-8 leaves the boundaries
        // intact and silently destroys the file's contents.
        form.append("file", file);
        form.append("resource_type", resourceType);
        // A single file may be renamed; a batch of them keeps its own names.
        if (files.length === 1 && name) form.append("name", name);
        if (folderId) form.append("folder_id", folderId);
        else {
          if (courseId) form.append("course_id", courseId);
          if (batchId) form.append("batch_id", batchId);
        }
        await api.post<ResourceResponse>("/resources", { body: form });
      }
      return files.length;
    },
    success: (count) => `Uploaded ${count} file(s).`,
    invalidate: [["resources"]],
    onSuccess: () => {
      setFiles([]);
      setName("");
      if (inputRef.current) inputRef.current.value = "";
      void queryClient.invalidateQueries({ queryKey: ["folders"] });
      onOpenChange(false);
    },
  });

  // Mirrors the server's rule so the button is disabled rather than the request
  // refused; the server remains the authority.
  const anchored = !atRoot || courseId !== "" || batchId !== "";
  const ready = files.length > 0 && anchored;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="md">
        <DialogHeader
          title={files.length > 1 ? `Upload ${files.length} files` : "Upload a file"}
          description={
            atRoot
              ? "A file at the top level belongs to a course or a batch — that is what decides who can reach it."
              : `Into ${folderName}. It inherits that folder's course and batch.`
          }
        />
        <div className="space-y-4">
          <Field label="File" required>
            {({ id }) => (
              <input
                id={id}
                ref={inputRef}
                type="file"
                multiple
                className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm"
                onChange={(event) => {
                  const chosen = Array.from(event.target.files ?? []);
                  setFiles(chosen);
                  if (chosen.length === 1 && !name) setName(chosen[0]?.name ?? "");
                }}
              />
            )}
          </Field>

          <FormGrid>
            {files.length <= 1 ? (
              <Field label="Display name">
                {({ id }) => (
                  <Input id={id} value={name} onChange={(event) => setName(event.target.value)} />
                )}
              </Field>
            ) : null}
            <Field label="Type">
              {({ id }) => (
                <Select
                  id={id}
                  value={resourceType}
                  onValueChange={(next) => setResourceType((next ?? ""))}
                 options={optionsFromValues(ResourceTypeValues)} />
              )}
            </Field>
          </FormGrid>

          {atRoot ? (
            <FormGrid>
              <Field label="Course">
                {({ id }) => (
                  <CoursePicker id={id} value={(courseId) || null} onValueChange={(next) => setCourseId((next ?? ""))} placeholder="No course" clearable />
                )}
              </Field>
              <Field label="Batch">
                {({ id }) => (
                  <BatchPicker id={id} value={(batchId) || null} onValueChange={(next) => setBatchId((next ?? ""))} placeholder="No batch" clearable />
                )}
              </Field>
            </FormGrid>
          ) : null}

          {atRoot && !anchored && files.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              Choose a course, a batch, or both. A file attached to neither would be
              reachable by nobody.
            </p>
          ) : null}

          {files.length > 0 ? (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {files.map((file) => (
                <li key={`${file.name}-${file.size}`}>
                  {file.name} · {formatBytes(file.size)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={upload.isPending} disabled={!ready} onClick={() => upload.mutate()}>
            <Upload /> Upload
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
