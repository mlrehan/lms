"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Loader2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { uploadFileWithProgress } from "@/lib/api/client";
import type { ResourceResponse } from "@/lib/api/types";
import { ResourceTypeValues } from "@/lib/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { Badge } from "@/components/ui/primitives";
import { formatBytes } from "@/components/domain/resources/drive-view";
import { BatchPicker, CoursePicker } from "@/components/domain/entity-pickers";

export type UploadItemStatus = "pending" | "uploading" | "completed" | "failed";

export interface FileUploadItem {
  id: string;
  file: File;
  progress: number;
  status: UploadItemStatus;
  error?: string;
}

function getFileSignature(file: File): string {
  return `${file.name}-${file.size}-${file.lastModified}`;
}

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
  initialFiles?: File[];
}) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const [items, setItems] = useState<FileUploadItem[]>([]);
  const [name, setName] = useState("");
  const [resourceType, setResourceType] = useState<string>("Document");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [isUploading, setIsUploading] = useState(false);

  const atRoot = folderId === null;

  function addFiles(newFiles: File[]) {
    setItems((existing) => {
      const existingSignatures = new Set(existing.map((item) => item.id));
      const added: FileUploadItem[] = [];
      let duplicatesCount = 0;

      for (const file of newFiles) {
        const sig = getFileSignature(file);
        if (existingSignatures.has(sig)) {
          duplicatesCount++;
          continue;
        }
        existingSignatures.add(sig);
        added.push({
          id: sig,
          file,
          progress: 0,
          status: "pending",
        });
      }

      if (duplicatesCount > 0) {
        toast.warning(
          `${duplicatesCount} duplicate file(s) were automatically skipped to prevent duplicate uploads.`
        );
      }

      const combined = [...existing, ...added];
      if (combined.length === 1 && !name) {
        setName(combined[0]?.file.name ?? "");
      }
      return combined;
    });
  }

  // Adopt dropped or initial files
  const [seed, setSeed] = useState<File[] | undefined>(initialFiles);
  if (seed !== initialFiles) {
    setSeed(initialFiles);
    if (initialFiles && initialFiles.length > 0) {
      addFiles(initialFiles);
    }
  }

  useEffect(() => {
    if (!open) {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      setIsUploading(false);
      setItems([]);
      setName("");
      if (inputRef.current) inputRef.current.value = "";
    }
  }, [open]);

  function removeItem(id: string) {
    if (isUploading) return;
    setItems((current) => current.filter((item) => item.id !== id));
  }

  async function handleUpload() {
    if (items.length === 0 || isUploading) return;

    const pendingItems = items.filter((item) => item.status !== "completed");
    if (pendingItems.length === 0) {
      toast.info("All files have already been uploaded.");
      return;
    }

    setIsUploading(true);
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    let successCount = 0;
    let failureCount = 0;

    for (const item of pendingItems) {
      if (signal.aborted) break;

      setItems((prev) =>
        prev.map((i) =>
          i.id === item.id ? { ...i, status: "uploading", progress: 0, error: undefined } : i
        )
      );

      const form = new FormData();
      form.append("file", item.file);
      form.append("resource_type", resourceType);

      if (items.length === 1 && name.trim()) {
        form.append("name", name.trim());
      } else {
        form.append("name", item.file.name);
      }

      if (folderId) {
        form.append("folder_id", folderId);
      } else {
        if (courseId) form.append("course_id", courseId);
        if (batchId) form.append("batch_id", batchId);
      }

      try {
        await uploadFileWithProgress<ResourceResponse>(
          "/resources",
          form,
          (percent) => {
            setItems((prev) =>
              prev.map((i) => (i.id === item.id ? { ...i, progress: percent } : i))
            );
          },
          { signal }
        );

        setItems((prev) =>
          prev.map((i) =>
            i.id === item.id ? { ...i, status: "completed", progress: 100 } : i
          )
        );
        successCount++;
      } catch (err: unknown) {
        if (signal.aborted) {
          setItems((prev) =>
            prev.map((i) =>
              i.id === item.id ? { ...i, status: "pending", progress: 0 } : i
            )
          );
          break;
        }

        const msg = err instanceof Error ? err.message : "Upload failed";
        setItems((prev) =>
          prev.map((i) =>
            i.id === item.id ? { ...i, status: "failed", error: msg } : i
          )
        );
        failureCount++;
      }
    }

    setIsUploading(false);
    void queryClient.invalidateQueries({ queryKey: ["resources"] });
    void queryClient.invalidateQueries({ queryKey: ["folders"] });

    if (successCount > 0 && failureCount === 0) {
      toast.success(`Successfully uploaded ${successCount} file(s).`);
      onOpenChange(false);
    } else if (successCount > 0 && failureCount > 0) {
      toast.warning(`Uploaded ${successCount} file(s), but ${failureCount} file(s) failed.`);
    } else if (failureCount > 0) {
      toast.error(`Failed to upload ${failureCount} file(s).`);
    }
  }

  const anchored = !atRoot || courseId !== "" || batchId !== "";
  const totalFiles = items.length;
  const completedCount = items.filter((i) => i.status === "completed").length;
  const totalProgress =
    totalFiles > 0
      ? Math.round(
          items.reduce((acc, curr) => acc + (curr.progress || 0), 0) / totalFiles
        )
      : 0;

  const allCompleted = totalFiles > 0 && completedCount === totalFiles;
  const readyToUpload = totalFiles > 0 && anchored && !isUploading && !allCompleted;

  return (
    <Dialog open={open} onOpenChange={(next) => (isUploading ? null : onOpenChange(next))}>
      <DialogContent size="md">
        <DialogHeader
          title={totalFiles > 1 ? `Upload ${totalFiles} files` : "Upload a file"}
          description={
            atRoot
              ? "A file at the top level belongs to a course or a batch — that is what decides who can reach it."
              : `Into ${folderName}. It inherits that folder's course and batch.`
          }
        />
        <div className="space-y-4">
          <Field label="Choose file(s)" required>
            {({ id }) => (
              <input
                id={id}
                ref={inputRef}
                type="file"
                multiple
                disabled={isUploading}
                className="w-full rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm disabled:cursor-not-allowed disabled:opacity-50"
                onChange={(event) => {
                  const chosen = Array.from(event.target.files ?? []);
                  if (chosen.length > 0) addFiles(chosen);
                }}
              />
            )}
          </Field>

          <FormGrid>
            {totalFiles <= 1 ? (
              <Field label="Display name">
                {({ id }) => (
                  <Input
                    id={id}
                    value={name}
                    disabled={isUploading}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Defaults to original filename"
                  />
                )}
              </Field>
            ) : null}
            <Field label="Type">
              {({ id }) => (
                <Select
                  id={id}
                  value={resourceType}
                  disabled={isUploading}
                  onValueChange={(next) => setResourceType(next ?? "Document")}
                  options={optionsFromValues(ResourceTypeValues)}
                />
              )}
            </Field>
          </FormGrid>

          {atRoot ? (
            <FormGrid>
              <Field label="Course">
                {({ id }) => (
                  <CoursePicker
                    id={id}
                    value={courseId || null}
                    disabled={isUploading}
                    onValueChange={(next) => setCourseId(next ?? "")}
                    placeholder="No course"
                    clearable
                  />
                )}
              </Field>
              <Field label="Batch">
                {({ id }) => (
                  <BatchPicker
                    id={id}
                    value={batchId || null}
                    disabled={isUploading}
                    onValueChange={(next) => setBatchId(next ?? "")}
                    placeholder="No batch"
                    clearable
                  />
                )}
              </Field>
            </FormGrid>
          ) : null}

          {atRoot && !anchored && totalFiles > 0 ? (
            <p className="text-xs text-danger">
              Please choose a course, a batch, or both. Unanchored root files are refused.
            </p>
          ) : null}

          {totalFiles > 0 ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
                <span>
                  {completedCount} of {totalFiles} files completed
                </span>
                <span>{totalProgress}%</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${totalProgress}%` }}
                />
              </div>

              <div className="max-h-48 divide-y divide-border-subtle overflow-y-auto rounded-lg border border-border-subtle">
                {items.map((item) => (
                  <div
                    key={item.id}
                    className="flex flex-col gap-1 p-2.5 text-xs transition-colors hover:bg-muted/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium text-foreground">
                        {item.file.name}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <span className="text-muted-foreground">
                          {formatBytes(item.file.size)}
                        </span>
                        {item.status === "pending" && (
                          <Badge tone="neutral">Queued</Badge>
                        )}
                        {item.status === "uploading" && (
                          <Badge tone="primary" className="flex items-center gap-1">
                            <Loader2 className="size-3 animate-spin" />
                            {item.progress}%
                          </Badge>
                        )}
                        {item.status === "completed" && (
                          <Badge tone="success" className="flex items-center gap-1">
                            <CheckCircle2 className="size-3" />
                            Done
                          </Badge>
                        )}
                        {item.status === "failed" && (
                          <Badge tone="danger" className="flex items-center gap-1">
                            <AlertCircle className="size-3" />
                            Failed
                          </Badge>
                        )}
                        {!isUploading && item.status !== "completed" && (
                          <button
                            type="button"
                            onClick={() => removeItem(item.id)}
                            className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                            aria-label={`Remove ${item.file.name}`}
                          >
                            <X className="size-3.5" />
                          </button>
                        )}
                      </div>
                    </div>

                    {item.status === "uploading" ? (
                      <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full bg-primary transition-all duration-200"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    ) : null}

                    {item.error ? (
                      <p className="text-2xs text-danger">{item.error}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
        <DialogFooter>
          <Button
            variant="ghost"
            disabled={isUploading}
            onClick={() => onOpenChange(false)}
          >
            {allCompleted ? "Close" : "Cancel"}
          </Button>
          <Button
            loading={isUploading}
            disabled={!readyToUpload}
            onClick={() => void handleUpload()}
          >
            <Upload className="size-4" />
            {isUploading
              ? `Uploading (${totalProgress}%)...`
              : allCompleted
                ? "Completed"
                : `Upload ${totalFiles > 0 ? `(${totalFiles})` : ""}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
