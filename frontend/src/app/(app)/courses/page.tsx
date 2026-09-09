"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import type {
  CategoryResponse,
  CourseResponse,
  CourseSummary,
  DepartmentResponse,
  PageCategoryResponse,
  PageCourseSummary,
  PageDepartmentResponse,
  PageTagResponse,
} from "@/lib/api/types";
import { CourseStatusValues, LevelsValues } from "@/lib/api/types";
import { applyFieldErrors, useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, FormGrid, Input, NativeSelect, Textarea } from "@/components/ui/form";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { useSession } from "@/lib/auth/session";
import { humanise } from "@/lib/utils";

const createSchema = z.object({
  title: z.string().trim().min(2, "Give the course a title."),
  code: z.string().trim().optional(),
  level: z.enum(LevelsValues),
  description: z.string().trim().optional(),
  duration_hours: z.string().trim().optional(),
  price: z.string().trim().optional(),
  category_id: z.string().trim().optional(),
  department_id: z.string().trim().optional(),
});

type CreateValues = z.infer<typeof createSchema>;

function numberOrNull(value: string | undefined): number | null {
  if (!value || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function CreateCourseDialog({
  open,
  onOpenChange,
  categories,
  departments,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: CategoryResponse[];
  departments: DepartmentResponse[];
}) {
  const router = useRouter();
  const [banner, setBanner] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { title: "", level: "BEGINNER" },
  });

  const create = useApiMutation<CourseResponse, CreateValues>({
    mutationFn: (values) =>
      api.post<CourseResponse>("/courses", {
        body: {
          title: values.title,
          code: values.code || null,
          description: values.description || null,
          level: values.level,
          duration_hours: numberOrNull(values.duration_hours),
          price: numberOrNull(values.price),
          category_id: values.category_id || null,
          department_id: values.department_id || null,
        },
      }),
    success: (course) => `Created "${course.title}". It starts as a draft.`,
    invalidate: [["courses"]],
    onSuccess: (course) => {
      reset();
      onOpenChange(false);
      router.push(`/courses/${course.public_id}`);
    },
    onError: (error) => {
      if (!applyFieldErrors<CreateValues>(error, setError, ["title", "code", "level"])) {
        setBanner(error.message);
      }
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          title="Create a course"
          description="A new course starts in DRAFT and is invisible to students until it is published."
        />
        <form onSubmit={handleSubmit((values) => create.mutate(values))} className="space-y-4" noValidate>
          {banner ? (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {banner}
            </div>
          ) : null}
          <FormGrid>
            <Field label="Title" error={errors.title?.message} required>
              {({ id }) => <Input id={id} {...register("title")} />}
            </Field>
            <Field label="Code" error={errors.code?.message} hint="Unique across the institution.">
              {({ id }) => <Input id={id} placeholder="MATH101" {...register("code")} />}
            </Field>
            <Field label="Level" required>
              {({ id }) => (
                <NativeSelect id={id} {...register("level")}>
                  {LevelsValues.map((level) => (
                    <option key={level} value={level}>
                      {humanise(level)}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Duration (hours)">
              {({ id }) => <Input id={id} type="number" min={0} {...register("duration_hours")} />}
            </Field>
            <Field label="Category">
              {({ id }) => (
                <NativeSelect id={id} {...register("category_id")}>
                  <option value="">Uncategorised</option>
                  {categories.map((category) => (
                    <option key={category.public_id} value={category.public_id}>
                      {category.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Department">
              {({ id }) => (
                <NativeSelect id={id} {...register("department_id")}>
                  <option value="">None</option>
                  {departments.map((department) => (
                    <option key={department.public_id} value={department.public_id}>
                      {department.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          <Field label="Description">
            {({ id }) => <Textarea id={id} {...register("description")} />}
          </Field>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create course
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function CoursesPage() {
  const { permissions } = useSession();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();
  const [status, setStatus] = useState("");
  const [level, setLevel] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [tagId, setTagId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["courses", "list", debouncedSearch, status, level, categoryId, departmentId, tagId, limit, offset],
    queryFn: () =>
      api.get<PageCourseSummary>("/courses", {
        query: {
          query: debouncedSearch || undefined,
          status: status || undefined,
          level: level || undefined,
          category_id: categoryId || undefined,
          department_id: departmentId || undefined,
          tag_id: tagId || undefined,
          limit,
          offset,
        },
      }),
  });

  const canReadAcademic = permissions.has("academic.read");

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

  const tags = useQuery({
    queryKey: ["tags", "all"],
    queryFn: () => api.get<PageTagResponse>("/tags", { query: { limit: 200 } }),
    enabled: canReadAcademic,
    staleTime: 5 * 60_000,
  });

  const columns: Column<CourseSummary>[] = [
    {
      key: "title",
      header: "Course",
      cell: (course) => (
        <div className="min-w-0">
          <Link href={`/courses/${course.public_id}`} className="font-medium hover:underline">
            {course.title}
          </Link>
          {course.code ? (
            <p className="font-mono text-xs text-muted-foreground">{course.code}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (course) => <StatusBadge value={course.status} kind="course" />,
    },
    {
      key: "level",
      header: "Level",
      secondary: true,
      cell: (course) => <Badge tone="neutral">{humanise(course.level)}</Badge>,
    },
    {
      key: "duration",
      header: "Hours",
      align: "right",
      secondary: true,
      cell: (course) => (
        <span className="tabular-nums">{course.duration_hours ?? "—"}</span>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Courses"
        description="The catalog. A course moves Draft -> Published -> Running -> Completed -> Archived; the server enforces which transitions are legal."
        actions={
          permissions.has("course.create") ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus /> New course
            </Button>
          ) : null
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
          <div className="relative min-w-56 flex-1">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search courses"
              aria-label="Search courses"
              className="pl-8"
            />
          </div>
          <NativeSelect
            className="w-auto"
            value={status}
            aria-label="Filter by status"
            onChange={(event) => {
              setStatus(event.target.value);
              setPage({ limit, offset: 0 });
            }}
          >
            <option value="">Any status</option>
            {CourseStatusValues.map((value) => (
              <option key={value} value={value}>
                {humanise(value)}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            className="w-auto"
            value={level}
            aria-label="Filter by level"
            onChange={(event) => {
              setLevel(event.target.value);
              setPage({ limit, offset: 0 });
            }}
          >
            <option value="">Any level</option>
            {LevelsValues.map((value) => (
              <option key={value} value={value}>
                {humanise(value)}
              </option>
            ))}
          </NativeSelect>
          {canReadAcademic ? (
            <>
              <NativeSelect
                className="w-auto"
                value={categoryId}
                aria-label="Filter by category"
                onChange={(event) => {
                  setCategoryId(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any category</option>
                {(categories.data?.items ?? []).map((category) => (
                  <option key={category.public_id} value={category.public_id}>
                    {category.name}
                  </option>
                ))}
              </NativeSelect>
              <NativeSelect
                className="w-auto"
                value={departmentId}
                aria-label="Filter by department"
                onChange={(event) => {
                  setDepartmentId(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any department</option>
                {(departments.data?.items ?? []).map((department) => (
                  <option key={department.public_id} value={department.public_id}>
                    {department.name}
                  </option>
                ))}
              </NativeSelect>
              <NativeSelect
                className="w-auto"
                value={tagId}
                aria-label="Filter by tag"
                onChange={(event) => {
                  setTagId(event.target.value);
                  setPage({ limit, offset: 0 });
                }}
              >
                <option value="">Any tag</option>
                {(tags.data?.items ?? []).map((tag) => (
                  <option key={tag.public_id} value={tag.public_id}>
                    {tag.name}
                  </option>
                ))}
              </NativeSelect>
            </>
          ) : null}
        </div>

        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(course) => course.public_id}
              emptyMessage="No courses match these filters."
            />
            <Pagination
              total={data?.total ?? 0}
              limit={limit}
              offset={offset}
              onChange={setPage}
              label="courses"
            />
          </>
        )}
      </Card>

      <CreateCourseDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        categories={categories.data?.items ?? []}
        departments={departments.data?.items ?? []}
      />
    </div>
  );
}
