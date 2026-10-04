"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Save, Sparkles, Undo2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, segment } from "@/lib/api/client";
import type {
  CategoryResponse,
  CodeSuggestion,
  CourseResponse,
  DepartmentResponse,
  LinkPreviewResponse,
  PageCategoryResponse,
  PageDepartmentResponse,
} from "@/lib/api/types";
import { LevelsValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation } from "@/lib/api/hooks";
import { Button } from "@/components/ui/button";
import { Field, FormGrid, Input, Textarea } from "@/components/ui/form";
import { Select } from "@/components/ui/select";
import { FormSelect } from "@/components/ui/form-controls";
import { CourseImagePicker, type StagedImage } from "@/components/domain/course-image-picker";
import { AddCategoryDialog, AddDepartmentDialog } from "@/components/domain/course-reference-dialogs";
import { useSession } from "@/lib/auth/session";
import { humanise } from "@/lib/utils";

const ADD = "__add__";

const isNumber = (v: string) => v === "" || (Number.isFinite(Number(v)) && Number(v) >= 0);

const schema = z.object({
  title: z.string().trim().min(3, "Give the course a title of at least 3 characters.").max(255),
  code: z
    .string()
    .trim()
    .max(30, "Use 30 characters or fewer.")
    .regex(/^[A-Za-z0-9._-]*$/, "Letters, numbers, dots, dashes and underscores only."),
  level: z.enum(LevelsValues),
  duration_hours: z.string().trim().refine((v) => isNumber(v) && (v === "" || Number.isInteger(Number(v))), "Enter a whole number of hours."),
  price: z.string().trim().refine(isNumber, "Enter a price of zero or more."),
  course_link: z
    .string()
    .trim()
    .max(255, "Use 255 characters or fewer.")
    .refine((v) => v === "" || /^https?:\/\/\S+$/i.test(v), "Start with http:// or https://"),
  category_id: z.string(),
  department_id: z.string(),
  description: z.string().trim(),
  prerequisites: z.string().trim(),
});

type Values = z.infer<typeof schema>;

function numberOrNull(value: string): number | null {
  return value.trim() === "" ? null : Number(value);
}

function toValues(course?: CourseResponse): Values {
  return {
    title: course?.title ?? "",
    code: course?.code ?? "",
    level: course?.level ?? "BEGINNER",
    duration_hours: course?.duration_hours?.toString() ?? "",
    price: course?.price?.toString() ?? "",
    course_link: course?.course_link ?? "",
    category_id: course?.category_id ?? "",
    department_id: course?.department_id ?? "",
    description: course?.description ?? "",
    prerequisites: course?.prerequisites ?? "",
  };
}

export const gbp = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

/**
 * One form for creating a course and for editing one.
 *
 * - **Images are staged, then sent after the course is saved.** A course being
 *   created has no id to upload to yet, and a cancelled form should upload nothing.
 * - **The code is suggested from the title** until the person types their own; the
 *   server checks uniqueness, so a suggestion is never a reservation.
 * - **"Fetch from link"** reads the course page and fills fields that are still
 *   empty. It never overwrites something the person entered, and it saves nothing.
 * - **Category and department can be added on the spot** (needs `academic.create`).
 */
export function CourseForm({
  mode,
  course,
  canEdit = true,
  onSaved,
  onCancel,
}: {
  mode: "create" | "edit";
  course?: CourseResponse;
  canEdit?: boolean;
  onSaved: (course: CourseResponse) => void;
  onCancel?: () => void;
}) {
  const { permissions } = useSession();
  const canReadAcademic = permissions.has("academic.read");
  const canAddReference = permissions.has("academic.create");

  const {
    register, handleSubmit, control, reset, setValue, setError, getValues, watch,
    formState: { errors, isDirty, dirtyFields },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(course) });

  const [banner, setBanner] = useState<string | null>(null);
  const [small, setSmall] = useState<StagedImage>(null);
  const [full, setFull] = useState<StagedImage>(null);
  const [codeTouched, setCodeTouched] = useState(false);
  const [codeSuggested, setCodeSuggested] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [addCategory, setAddCategory] = useState(false);
  const [addDepartment, setAddDepartment] = useState(false);
  const [extraCategories, setExtraCategories] = useState<CategoryResponse[]>([]);
  const [extraDepartments, setExtraDepartments] = useState<DepartmentResponse[]>([]);

  const title = watch("title");
  const categoryId = watch("category_id");
  const departmentId = watch("department_id");
  const link = watch("course_link");
  const stagedImages = small !== null || full !== null;
  const changed = isDirty || stagedImages;
  const disabled = !canEdit;

  const categories = useQuery({
    queryKey: ["categories", "all"],
    queryFn: () => api.get<PageCategoryResponse>("/categories", { query: { limit: 200 } }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });
  const departments = useQuery({
    queryKey: ["departments", "all"],
    queryFn: () => api.get<PageDepartmentResponse>("/departments", { query: { limit: 200 } }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });

  const categoryOptions = mergeById([...(categories.data?.items ?? []), ...extraCategories]);
  const departmentOptions = mergeById([...(departments.data?.items ?? []), ...extraDepartments]);

  // ---- suggest a code while the person has not chosen their own
  const wantsSuggestion = canEdit && !codeTouched && (mode === "create" || !course?.code);
  useEffect(() => {
    if (!wantsSuggestion || title.trim().length < 3) return;
    const timer = setTimeout(async () => {
      try {
        const result = await api.get<CodeSuggestion>("/courses/suggest-code", { query: { title: title.trim() } });
        setValue("code", result.code, { shouldDirty: true });
        setCodeSuggested(true);
      } catch {
        // A suggestion is a convenience; failing to get one must not get in the way.
      }
    }, 450);
    return () => clearTimeout(timer);
  }, [title, wantsSuggestion, setValue]);

  // ---- read the course page
  async function fetchFromLink(options: { quiet?: boolean; only?: "price" } = {}) {
    const url = getValues("course_link").trim();
    if (!url) return;
    setFetching(true);
    try {
      const page = await api.post<LinkPreviewResponse>("/courses/link-preview", { body: { url } });
      const filled: string[] = [];
      const differs: string[] = [];
      const apply = (name: "price" | "duration_hours" | "prerequisites", value: string | null | undefined, label: string) => {
        if (value === null || value === undefined || value === "") return;
        const current = getValues(name).trim();
        if (current === "") {
          setValue(name, value, { shouldDirty: true });
          filled.push(label);
        } else if (current !== value) {
          differs.push(`${label} on the page is ${name === "price" ? gbp.format(Number(value)) : value}`);
        }
      };
      apply("price", page.price?.toString(), "price");
      if (options.only !== "price") {
        apply("duration_hours", page.duration_hours?.toString(), "duration");
        apply("prerequisites", page.prerequisites, "prerequisites");
        if (mode === "create" && !dirtyFields.level && page.level && page.level !== getValues("level")) {
          setValue("level", page.level, { shouldDirty: true });
          filled.push("level");
        }
      }
      if (filled.length) toast.success(`Filled from the course page: ${filled.join(", ")}. Review, then save.`);
      else if (!options.quiet) toast.info(differs.length ? `Nothing was empty to fill. ${differs.join("; ")}.` : "The page has nothing new to fill in.");
    } catch (error) {
      if (!options.quiet) toast.error(error instanceof Error ? error.message : "Could not read the page.");
    } finally {
      setFetching(false);
    }
  }

  // An existing course with a link but no price is the common result of an import: offer the price without being asked.
  useEffect(() => {
    if (mode === "edit" && canEdit && course?.course_link && course.price == null) {
      void fetchFromLink({ quiet: true, only: "price" });
    }
    // Once, on open: re-running it on every keystroke would fight the person editing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- save
  const save = useApiMutation<CourseResponse, Values>({
    mutationFn: async (values) => {
      const body = {
        title: values.title,
        code: values.code || null,
        description: values.description || null,
        level: values.level,
        duration_hours: numberOrNull(values.duration_hours),
        price: numberOrNull(values.price),
        prerequisites: values.prerequisites || null,
        course_link: values.course_link || null,
        category_id: values.category_id || null,
        department_id: values.department_id || null,
        ...(mode === "edit"
          ? {
              // "leave alone" and "clear" are different requests to this API.
              clear_category: values.category_id === "" && course?.category_id != null,
              clear_department: values.department_id === "" && course?.department_id != null,
            }
          : {}),
      };
      let saved =
        mode === "create"
          ? await api.post<CourseResponse>("/courses", { body })
          : await api.patch<CourseResponse>(`/courses/${segment(course!.public_id)}`, { body });

      // The course itself is saved. A failed image must not undo that, so failures are reported, not thrown.
      const problems: string[] = [];
      for (const [kind, staged] of [["small", small], ["full", full]] as const) {
        if (staged === null) continue;
        try {
          if (staged === "remove") {
            saved = await api.delete<CourseResponse>(`/courses/${segment(saved.public_id)}/image/${kind}`);
          } else {
            const form = new FormData();
            form.append("file", staged);
            saved = await api.put<CourseResponse>(`/courses/${segment(saved.public_id)}/image/${kind}`, { body: form });
          }
        } catch (error) {
          problems.push(`${kind === "small" ? "Thumbnail" : "Main image"}: ${error instanceof Error ? error.message : "failed"}`);
        }
      }
      if (problems.length) toast.warning(`Course saved, but an image was not: ${problems.join("; ")}. Try again from the course page.`);
      return saved;
    },
    success: (saved) => (mode === "create" ? `Created "${saved.title}". It starts as a draft.` : "Course saved."),
    invalidate: [["courses"]],
    onSuccess: (saved) => {
      setSmall(null);
      setFull(null);
      setBanner(null);
      reset(toValues(saved));
      onSaved(saved);
    },
    onError: (error) => {
      if (!applyFieldErrors<Values>(error, setError, ["title", "code", "level", "course_link", "price", "category_id", "department_id"])) {
        setBanner(error.message);
      }
    },
  });

  return (
    <>
      <form method="post" onSubmit={handleSubmit((values) => save.mutate(values))} noValidate className="space-y-5">
        {banner ? (
          <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {banner}
          </div>
        ) : null}

        <section className="grid gap-5 sm:grid-cols-[auto_1fr]" aria-label="Images">
          <CourseImagePicker
            label="Thumbnail"
            hint="Shown in lists. Fits 320 x 320."
            current={course?.small_course_image}
            staged={small}
            onChange={setSmall}
            disabled={disabled}
          />
          <CourseImagePicker
            label="Main image"
            hint="Shown on the course page. Fits 1600 x 1200. JPEG, PNG or WebP, up to 5 MB."
            current={course?.course_image}
            staged={full}
            onChange={setFull}
            disabled={disabled}
            wide
          />
        </section>

        <FormGrid>
          <Field label="Title" error={errors.title?.message} required>
            {({ id }) => <Input id={id} disabled={disabled} autoFocus={mode === "create"} {...register("title")} />}
          </Field>
          <Field
            label="Code"
            error={errors.code?.message}
            hint={
              codeSuggested && !codeTouched
                ? "Suggested from the title. Change it if you like."
                : "Unique across the institution. Leave empty to have one generated."
            }
          >
            {({ id }) => (
              <div className="flex gap-1.5">
                <Input
                  id={id}
                  disabled={disabled}
                  className="font-mono"
                  {...register("code", {
                    onChange: () => {
                      setCodeTouched(true);
                      setCodeSuggested(false);
                    },
                  })}
                />
                {canEdit ? (
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label="Suggest a code from the title"
                    title="Suggest a code from the title"
                    disabled={title.trim().length < 3}
                    onClick={async () => {
                      try {
                        const r = await api.get<CodeSuggestion>("/courses/suggest-code", { query: { title: title.trim() } });
                        setValue("code", r.code, { shouldDirty: true });
                        setCodeSuggested(true);
                        setCodeTouched(false);
                      } catch (error) {
                        toast.error(error instanceof Error ? error.message : "Could not suggest a code.");
                      }
                    }}
                  >
                    <Wand2 />
                  </Button>
                ) : null}
              </div>
            )}
          </Field>

          <Field label="Level">
            {({ id }) => (
              <FormSelect id={id} disabled={disabled}  control={control} name="level" options={LevelsValues.map((level) => ({ value: level, label: humanise(level) }))} />
            )}
          </Field>
          <Field label="Duration (hours)" error={errors.duration_hours?.message}>
            {({ id }) => <Input id={id} type="number" min={0} step={1} disabled={disabled} {...register("duration_hours")} />}
          </Field>

          <Field label="Price (GBP)" error={errors.price?.message} hint="The regular price of the whole course.">
            {({ id }) => <Input id={id} type="number" min={0} step="0.01" disabled={disabled} {...register("price")} />}
          </Field>
          <Field label="Course link" error={errors.course_link?.message} hint="The course's page on the website.">
            {({ id }) => (
              <div className="flex gap-1.5">
                <Input id={id} type="url" placeholder="https://" disabled={disabled} {...register("course_link")} />
                {canEdit ? (
                  <Button
                    type="button"
                    variant="secondary"
                    loading={fetching}
                    disabled={!/^https?:\/\/\S+$/i.test(link.trim())}
                    title="Read the price, duration, level and prerequisites from this page"
                    onClick={() => void fetchFromLink()}
                  >
                    <Sparkles /> Fetch
                  </Button>
                ) : null}
              </div>
            )}
          </Field>

          <Field label="Category" error={errors.category_id?.message}>
            {({ id }) => (
              <Select
                id={id}
                disabled={disabled || !canReadAcademic}
                value={categoryId || null}
                placeholder="Uncategorised"
                clearable
                onValueChange={(next) => {
                  // `ADD` is a sentinel option that opens a dialog rather than
                  // selecting a value, so it must never reach form state.
                  if (next === ADD) return setAddCategory(true);
                  setValue("category_id", next ?? "", { shouldDirty: true });
                }}
                options={[
                  ...categoryOptions.map((c) => ({ value: c.public_id, label: c.name })),
                  ...(canAddReference ? [{ value: ADD, label: "+ Add a new category…" }] : []),
                ]}
              />
            )}
          </Field>
          <Field label="Department" error={errors.department_id?.message}>
            {({ id }) => (
              <Select
                id={id}
                disabled={disabled || !canReadAcademic}
                value={departmentId || null}
                placeholder="None"
                clearable
                onValueChange={(next) => {
                  if (next === ADD) return setAddDepartment(true);
                  setValue("department_id", next ?? "", { shouldDirty: true });
                }}
                options={[
                  ...departmentOptions.map((d) => ({ value: d.public_id, label: d.name })),
                  ...(canAddReference ? [{ value: ADD, label: "+ Add a new department…" }] : []),
                ]}
              />
            )}
          </Field>
        </FormGrid>

        <Field label="Description">
          {({ id }) => <Textarea id={id} rows={4} disabled={disabled} {...register("description")} />}
        </Field>
        <Field label="Prerequisites" hint="What a learner should know or have before starting.">
          {({ id }) => <Textarea id={id} rows={3} disabled={disabled} {...register("prerequisites")} />}
        </Field>

        {canEdit ? (
          <div
            className={
              mode === "edit"
                ? "sticky bottom-3 z-10 flex items-center justify-between gap-3 rounded-xl border border-border-subtle bg-surface/85 px-4 py-3 shadow-lg backdrop-blur-md"
                : "flex items-center justify-end gap-2 pt-2"
            }
            role="region"
            aria-label="Save changes"
          >
            {mode === "edit" ? (
              <p className="text-sm text-muted-foreground" aria-live="polite">
                {changed ? "You have unsaved changes" : "All changes saved"}
              </p>
            ) : null}
            <div className="flex gap-2">
              {mode === "create" ? (
                <Button type="button" variant="ghost" onClick={onCancel}>
                  Cancel
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="ghost"
                  disabled={!changed || save.isPending}
                  onClick={() => {
                    reset();
                    setSmall(null);
                    setFull(null);
                  }}
                >
                  <Undo2 /> Discard
                </Button>
              )}
              <Button type="submit" loading={save.isPending} disabled={mode === "edit" && !changed}>
                <Save /> {mode === "create" ? "Create course" : "Save course"}
              </Button>
            </div>
          </div>
        ) : null}
      </form>

      {/* Outside the form element: React bubbles events through portals, and these have forms of their own. */}
      <AddCategoryDialog
        open={addCategory}
        onOpenChange={setAddCategory}
        categories={categoryOptions}
        onCreated={(category) => {
          setExtraCategories((list) => [...list, category]);
          setValue("category_id", category.public_id, { shouldDirty: true });
        }}
      />
      <AddDepartmentDialog
        open={addDepartment}
        onOpenChange={setAddDepartment}
        onCreated={(department) => {
          setExtraDepartments((list) => [...list, department]);
          setValue("department_id", department.public_id, { shouldDirty: true });
        }}
      />
    </>
  );
}

function mergeById<T extends { public_id: string }>(items: T[]): T[] {
  const seen = new Map<string, T>();
  for (const item of items) seen.set(item.public_id, item);
  return [...seen.values()];
}
