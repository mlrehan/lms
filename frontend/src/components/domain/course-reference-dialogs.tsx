"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import type { CategoryResponse, DepartmentResponse } from "@/lib/api/types";
import { useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/form";

/**
 * "The category I want is not there" without leaving the course form.
 *
 * These are nested inside the course dialog, so their forms must not submit the
 * outer one: each handles its own `submit` and stops propagation, and neither is
 * a DOM descendant of the course form element (dialogs render in a portal).
 */
export function AddCategoryDialog({
  open,
  onOpenChange,
  categories,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: CategoryResponse[];
  onCreated: (category: CategoryResponse) => void;
}) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useApiMutation<CategoryResponse, void>({
    mutationFn: () =>
      api.post<CategoryResponse>("/categories", { body: { name: name.trim(), parent_id: parent || null } }),
    success: (category) => `Category "${category.name}" added.`,
    invalidate: [["categories"]],
    onSuccess: (category) => {
      onCreated(category);
      setName("");
      setParent("");
      setError(null);
      onOpenChange(false);
    },
    onError: (e) => setError(e.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader title="Add a category" description="It is selected for this course as soon as it is created." />
        <form
          method="post"
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (name.trim().length < 2) return setError("Give the category a name.");
            create.mutate();
          }}
          noValidate
        >
          <Field label="Name" error={error ?? undefined} required>
            {({ id }) => <Input id={id} value={name} autoFocus onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Parent category" hint="Optional. Leave empty for a top-level category.">
            {({ id }) => (
              <Select id={id} value={(parent) || null} onValueChange={(next) => setParent((next ?? ""))} placeholder="None (top level)" clearable options={categories.map((c) => ({ value: c.public_id, label: c.name }))} />
            )}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Add category
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function AddDepartmentDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (department: DepartmentResponse) => void;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  const create = useApiMutation<DepartmentResponse, void>({
    mutationFn: () =>
      api.post<DepartmentResponse>("/departments", {
        body: { name: name.trim(), code: code.trim() || null },
      }),
    success: (department) => `Department "${department.name}" added.`,
    invalidate: [["departments"]],
    onSuccess: (department) => {
      onCreated(department);
      setName("");
      setCode("");
      setError(null);
      onOpenChange(false);
    },
    onError: (e) => setError(e.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader title="Add a department" description="It is selected for this course as soon as it is created." />
        <form
          method="post"
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            event.stopPropagation();
            if (name.trim().length < 2) return setError("Give the department a name.");
            create.mutate();
          }}
          noValidate
        >
          <Field label="Name" error={error ?? undefined} required>
            {({ id }) => <Input id={id} value={name} autoFocus onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Code" hint="Optional short code, up to 20 characters.">
            {({ id }) => <Input id={id} value={code} maxLength={20} onChange={(e) => setCode(e.target.value)} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Add department
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
