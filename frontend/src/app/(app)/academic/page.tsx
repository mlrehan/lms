"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, Star, Trash2 } from "lucide-react";
import { api, segment } from "@/lib/api/client";
import type {
  AcademicYearResponse,
  CategoryResponse,
  DepartmentResponse,
  PageAcademicYearResponse,
  PageCategoryResponse,
  PageDepartmentResponse,
  PageSemesterResponse,
  PageTagResponse,
  SemesterResponse,
  TagResponse,
} from "@/lib/api/types";
import { useApiMutation, useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Switch,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Field, FormActions, FormGrid, Input, NativeSelect } from "@/components/ui/form";
import { UserPicker } from "@/components/domain/user-picker";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useSession } from "@/lib/auth/session";
import { formatCalendarDate } from "@/lib/format/datetime";

/**
 * The reference data every other screen picks from: academic years and their
 * semesters, departments, the category tree and free-form tags.
 *
 * All five share one permission (`academic.*`), which is why they share one
 * screen rather than five entries in the sidebar.
 */

function AcademicYears() {
  const { permissions } = useSession();
  const canWrite = permissions.has("academic.create");
  const { limit, offset, setPage } = useListState(25);
  const [draft, setDraft] = useState({ label: "", start_date: "", end_date: "", is_current: false });
  const [removing, setRemoving] = useState<AcademicYearResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["academic-years", limit, offset],
    queryFn: () => api.get<PageAcademicYearResponse>("/academic-years", { query: { limit, offset } }),
  });

  const create = useApiMutation<AcademicYearResponse, typeof draft>({
    mutationFn: (values) => api.post<AcademicYearResponse>("/academic-years", { body: values }),
    success: "Academic year added.",
    invalidate: [["academic-years"]],
    onSuccess: () => setDraft({ label: "", start_date: "", end_date: "", is_current: false }),
  });

  const setCurrent = useApiMutation<AcademicYearResponse, string>({
    mutationFn: (yearId) =>
      api.patch<AcademicYearResponse>(`/academic-years/${segment(yearId)}`, {
        body: { is_current: true },
      }),
    success: "Current year updated.",
    invalidate: [["academic-years"]],
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (yearId) => api.delete<void>(`/academic-years/${segment(yearId)}`),
    success: "Academic year deleted.",
    invalidate: [["academic-years"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<AcademicYearResponse>[] = [
    {
      key: "label",
      header: "Year",
      cell: (row) => (
        <span className="flex items-center gap-2 font-medium">
          {row.label}
          {row.is_current ? <Badge tone="success">Current</Badge> : null}
        </span>
      ),
    },
    {
      key: "range",
      header: "Runs",
      cell: (row) => `${formatCalendarDate(row.start_date)} – ${formatCalendarDate(row.end_date)}`,
    },
    {
      key: "semesters",
      header: "Semesters",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.semester_count ?? 0}</span>,
    },
    {
      key: "batches",
      header: "Batches",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.batch_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <div className="flex items-center justify-end gap-1">
          {permissions.has("academic.update") && !row.is_current ? (
            <Button
              variant="ghost"
              size="sm"
              aria-label={`Make ${row.label} current`}
              onClick={() => setCurrent.mutate(row.public_id)}
            >
              <Star /> Make current
            </Button>
          ) : null}
          {permissions.has("academic.delete") ? (
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${row.label}`}
              // The API refuses to delete a year that still has batches; the
              // button stays enabled so the refusal, and its reason, is seen.
              onClick={() => setRemoving(row)}
            >
              <Trash2 className="text-danger" />
            </Button>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Academic years"
        description="Promoting a year to current demotes whichever held it. Exactly one year is current."
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="No academic years defined."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="years"
          />
        </>
      )}

      {canWrite ? (
        <CardBody className="border-t border-border">
          <FormGrid columns={3}>
            <Field label="Label" hint="e.g. 2025-2026">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.label}
                  onChange={(event) => setDraft({ ...draft, label: event.target.value })}
                />
              )}
            </Field>
            <Field label="Starts">
              {({ id }) => (
                <Input
                  id={id}
                  type="date"
                  value={draft.start_date}
                  onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
                />
              )}
            </Field>
            <Field label="Ends">
              {({ id }) => (
                <Input
                  id={id}
                  type="date"
                  value={draft.end_date}
                  onChange={(event) => setDraft({ ...draft, end_date: event.target.value })}
                />
              )}
            </Field>
          </FormGrid>
          <label className="mt-3 flex items-center gap-3 text-sm">
            <Switch
              checked={draft.is_current}
              onCheckedChange={(checked) => setDraft({ ...draft, is_current: checked })}
            />
            Make this the current year
          </label>
          <FormActions>
            <Button
              loading={create.isPending}
              disabled={!draft.label || !draft.start_date || !draft.end_date}
              onClick={() => create.mutate(draft)}
            >
              <Plus /> Add year
            </Button>
          </FormActions>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.label ?? "this year"}?`}
        description="Refused if any batch is still scheduled into it."
        confirmLabel="Delete year"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function Semesters() {
  const { permissions } = useSession();
  const canWrite = permissions.has("academic.create");
  const { limit, offset, setPage } = useListState(25);
  const [yearFilter, setYearFilter] = useState("");
  const [draft, setDraft] = useState({ academic_year_id: "", name: "", start_date: "", end_date: "" });
  const [removing, setRemoving] = useState<SemesterResponse | null>(null);

  const years = useQuery({
    queryKey: ["academic-years", "all"],
    queryFn: () => api.get<PageAcademicYearResponse>("/academic-years", { query: { limit: 100 } }),
    staleTime: 5 * 60_000,
  });

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["semesters", yearFilter, limit, offset],
    queryFn: () =>
      api.get<PageSemesterResponse>("/semesters", {
        query: { academic_year_id: yearFilter || undefined, limit, offset },
      }),
  });

  const create = useApiMutation<SemesterResponse, typeof draft>({
    mutationFn: (values) => api.post<SemesterResponse>("/semesters", { body: values }),
    success: "Semester added.",
    invalidate: [["semesters"], ["academic-years"]],
    onSuccess: () => setDraft({ ...draft, name: "", start_date: "", end_date: "" }),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (semesterId) => api.delete<void>(`/semesters/${segment(semesterId)}`),
    success: "Semester deleted.",
    invalidate: [["semesters"], ["academic-years"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<SemesterResponse>[] = [
    { key: "name", header: "Semester", cell: (row) => <span className="font-medium">{row.name}</span> },
    { key: "year", header: "Year", cell: (row) => row.academic_year_label ?? "—" },
    {
      key: "range",
      header: "Runs",
      secondary: true,
      cell: (row) => `${formatCalendarDate(row.start_date)} – ${formatCalendarDate(row.end_date)}`,
    },
    {
      key: "batches",
      header: "Batches",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.batch_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("academic.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${row.name}`}
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Semesters"
        description="Terms inside an academic year. A batch can be scheduled into one."
        actions={
          <NativeSelect
            className="w-52"
            aria-label="Filter by academic year"
            value={yearFilter}
            onChange={(event) => {
              setYearFilter(event.target.value);
              setPage({ limit, offset: 0 });
            }}
          >
            <option value="">Every year</option>
            {(years.data?.items ?? []).map((year) => (
              <option key={year.public_id} value={year.public_id}>
                {year.label}
              </option>
            ))}
          </NativeSelect>
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="No semesters defined."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="semesters"
          />
        </>
      )}

      {canWrite ? (
        <CardBody className="border-t border-border">
          <FormGrid>
            <Field label="Academic year" required>
              {({ id }) => (
                <NativeSelect
                  id={id}
                  value={draft.academic_year_id}
                  onChange={(event) => setDraft({ ...draft, academic_year_id: event.target.value })}
                >
                  <option value="">Choose a year</option>
                  {(years.data?.items ?? []).map((year) => (
                    <option key={year.public_id} value={year.public_id}>
                      {year.label}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
            <Field label="Name" hint="e.g. Fall, Spring. Unique within its year.">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              )}
            </Field>
            <Field label="Starts">
              {({ id }) => (
                <Input
                  id={id}
                  type="date"
                  value={draft.start_date}
                  onChange={(event) => setDraft({ ...draft, start_date: event.target.value })}
                />
              )}
            </Field>
            <Field label="Ends">
              {({ id }) => (
                <Input
                  id={id}
                  type="date"
                  value={draft.end_date}
                  onChange={(event) => setDraft({ ...draft, end_date: event.target.value })}
                />
              )}
            </Field>
          </FormGrid>
          <FormActions>
            <Button
              loading={create.isPending}
              disabled={
                !draft.academic_year_id || !draft.name || !draft.start_date || !draft.end_date
              }
              onClick={() => create.mutate(draft)}
            >
              <Plus /> Add semester
            </Button>
          </FormActions>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.name ?? "this semester"}?`}
        description="Refused if any batch is still scheduled into it."
        confirmLabel="Delete semester"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function Departments() {
  const { permissions } = useSession();
  const canWrite = permissions.has("academic.create");
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(25);
  const [draft, setDraft] = useState({ name: "", code: "", head_tutor_id: "" });
  const [removing, setRemoving] = useState<DepartmentResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["departments", debouncedSearch, limit, offset],
    queryFn: () =>
      api.get<PageDepartmentResponse>("/departments", {
        query: { q: debouncedSearch || undefined, limit, offset },
      }),
  });

  const create = useApiMutation<DepartmentResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<DepartmentResponse>("/departments", {
        body: {
          name: values.name,
          code: values.code || null,
          head_tutor_id: values.head_tutor_id || null,
        },
      }),
    success: "Department added.",
    invalidate: [["departments"]],
    onSuccess: () => setDraft({ name: "", code: "", head_tutor_id: "" }),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (departmentId) => api.delete<void>(`/departments/${segment(departmentId)}`),
    success: "Department deleted.",
    invalidate: [["departments"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<DepartmentResponse>[] = [
    { key: "name", header: "Department", cell: (row) => <span className="font-medium">{row.name}</span> },
    {
      key: "code",
      header: "Code",
      secondary: true,
      cell: (row) => <span className="font-mono text-xs">{row.code ?? "—"}</span>,
    },
    { key: "head", header: "Head tutor", cell: (row) => row.head_tutor_username ?? "Vacant" },
    {
      key: "courses",
      header: "Courses",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.course_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("academic.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${row.name}`}
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Departments"
        description="Faculties or schools. A course can belong to one."
        actions={
          <Input
            className="w-56"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search departments"
            aria-label="Search departments"
          />
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="No departments defined."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="departments"
          />
        </>
      )}

      {canWrite ? (
        <CardBody className="border-t border-border">
          <FormGrid columns={3}>
            <Field label="Name">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              )}
            </Field>
            <Field label="Code">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.code}
                  onChange={(event) => setDraft({ ...draft, code: event.target.value })}
                />
              )}
            </Field>
            <Field label="Head tutor" hint="Must hold the TUTOR role.">
              {({ id }) => (
                <UserPicker
                  id={id}
                  role="TUTOR"
                  value={draft.head_tutor_id || null}
                  onChange={(next) => setDraft({ ...draft, head_tutor_id: next ?? "" })}
                />
              )}
            </Field>
          </FormGrid>
          <FormActions>
            <Button loading={create.isPending} disabled={!draft.name} onClick={() => create.mutate(draft)}>
              <Plus /> Add department
            </Button>
          </FormActions>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.name ?? "this department"}?`}
        description="Courses in it are not deleted; they simply lose their department."
        confirmLabel="Delete department"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function Categories() {
  const { permissions } = useSession();
  const canWrite = permissions.has("academic.create");
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(25);
  const [draft, setDraft] = useState({ name: "", parent_id: "" });
  const [removing, setRemoving] = useState<CategoryResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["categories", debouncedSearch, limit, offset],
    queryFn: () =>
      api.get<PageCategoryResponse>("/categories", {
        query: { q: debouncedSearch || undefined, limit, offset },
      }),
  });

  const all = useQuery({
    queryKey: ["categories", "all"],
    queryFn: () => api.get<PageCategoryResponse>("/categories", { query: { limit: 200 } }),
    staleTime: 5 * 60_000,
  });

  const create = useApiMutation<CategoryResponse, typeof draft>({
    mutationFn: (values) =>
      api.post<CategoryResponse>("/categories", {
        body: { name: values.name, parent_id: values.parent_id || null },
      }),
    success: "Category added.",
    invalidate: [["categories"]],
    onSuccess: () => setDraft({ name: "", parent_id: "" }),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (categoryId) => api.delete<void>(`/categories/${segment(categoryId)}`),
    success: "Category deleted.",
    invalidate: [["categories"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<CategoryResponse>[] = [
    { key: "name", header: "Category", cell: (row) => <span className="font-medium">{row.name}</span> },
    { key: "parent", header: "Parent", cell: (row) => row.parent_name ?? "Top level" },
    {
      key: "children",
      header: "Sub-categories",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.child_count ?? 0}</span>,
    },
    {
      key: "courses",
      header: "Courses",
      align: "right",
      secondary: true,
      cell: (row) => <span className="tabular-nums">{row.course_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("academic.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${row.name}`}
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Categories"
        description="A tree. A course belongs to at most one category."
        actions={
          <Input
            className="w-56"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search categories"
            aria-label="Search categories"
          />
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="No categories defined."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="categories"
          />
        </>
      )}

      {canWrite ? (
        <CardBody className="border-t border-border">
          <FormGrid>
            <Field label="Name">
              {({ id }) => (
                <Input
                  id={id}
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              )}
            </Field>
            <Field label="Parent" hint="Leave blank for a top-level category.">
              {({ id }) => (
                <NativeSelect
                  id={id}
                  value={draft.parent_id}
                  onChange={(event) => setDraft({ ...draft, parent_id: event.target.value })}
                >
                  <option value="">Top level</option>
                  {(all.data?.items ?? []).map((category) => (
                    <option key={category.public_id} value={category.public_id}>
                      {category.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
            </Field>
          </FormGrid>
          <FormActions>
            <Button loading={create.isPending} disabled={!draft.name} onClick={() => create.mutate(draft)}>
              <Plus /> Add category
            </Button>
          </FormActions>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.name ?? "this category"}?`}
        description="Courses in it become uncategorised."
        confirmLabel="Delete category"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

function Tags() {
  const { permissions } = useSession();
  const canWrite = permissions.has("academic.create");
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState(25);
  const [name, setName] = useState("");
  const [removing, setRemoving] = useState<TagResponse | null>(null);

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["tags", debouncedSearch, limit, offset],
    queryFn: () =>
      api.get<PageTagResponse>("/tags", { query: { q: debouncedSearch || undefined, limit, offset } }),
  });

  const create = useApiMutation<TagResponse, string>({
    mutationFn: (value) => api.post<TagResponse>("/tags", { body: { name: value } }),
    success: "Tag added.",
    invalidate: [["tags"]],
    onSuccess: () => setName(""),
  });

  const remove = useApiMutation<void, string>({
    mutationFn: (tagId) => api.delete<void>(`/tags/${segment(tagId)}`),
    success: "Tag deleted.",
    invalidate: [["tags"]],
    onSuccess: () => setRemoving(null),
  });

  const columns: Column<TagResponse>[] = [
    { key: "name", header: "Tag", cell: (row) => <span className="font-medium">{row.name}</span> },
    {
      key: "courses",
      header: "Courses",
      align: "right",
      cell: (row) => <span className="tabular-nums">{row.course_count ?? 0}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        permissions.has("academic.delete") ? (
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${row.name}`}
            onClick={() => setRemoving(row)}
          >
            <Trash2 className="text-danger" />
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Tags"
        description="Free-form labels, independent of the category tree."
        actions={
          <Input
            className="w-56"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search tags"
            aria-label="Search tags"
          />
        }
      />
      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={data?.items ?? []}
            rowKey={(row) => row.public_id}
            emptyMessage="No tags defined."
          />
          <Pagination
            total={data?.total ?? 0}
            limit={limit}
            offset={offset}
            onChange={setPage}
            label="tags"
          />
        </>
      )}

      {canWrite ? (
        <CardBody className="flex items-end gap-2 border-t border-border">
          <Field label="New tag" className="max-w-xs flex-1">
            {({ id }) => (
              <Input id={id} value={name} onChange={(event) => setName(event.target.value)} />
            )}
          </Field>
          <Button
            className="mb-0.5"
            loading={create.isPending}
            disabled={name.trim() === ""}
            onClick={() => create.mutate(name.trim())}
          >
            <Plus /> Add tag
          </Button>
        </CardBody>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
        destructive
        title={`Delete ${removing?.name ?? "this tag"}?`}
        description="It is removed from every course that carries it."
        confirmLabel="Delete tag"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.public_id);
        }}
      />
    </Card>
  );
}

export default function AcademicSetupPage(): ReactNode {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Academic setup"
        description="The reference data everything else picks from: years, semesters, departments, categories and tags."
      />

      <Tabs defaultValue="years">
        <TabsList>
          <TabsTab value="years">Academic years</TabsTab>
          <TabsTab value="semesters">Semesters</TabsTab>
          <TabsTab value="departments">Departments</TabsTab>
          <TabsTab value="categories">Categories</TabsTab>
          <TabsTab value="tags">Tags</TabsTab>
        </TabsList>
        <TabsPanel value="years">
          <AcademicYears />
        </TabsPanel>
        <TabsPanel value="semesters">
          <Semesters />
        </TabsPanel>
        <TabsPanel value="departments">
          <Departments />
        </TabsPanel>
        <TabsPanel value="categories">
          <Categories />
        </TabsPanel>
        <TabsPanel value="tags">
          <Tags />
        </TabsPanel>
      </Tabs>
    </div>
  );
}
