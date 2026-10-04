"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Eye, Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import type {
  CourseSummary,
  PageCategoryResponse,
  PageCourseSummary,
} from "@/lib/api/types";
import { CourseStatusValues, LevelsValues } from "@/lib/api/types";
import { useListState } from "@/lib/api/hooks";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { Column, DataTable, Pagination } from "@/components/ui/data-table";
import { Dialog, DialogContent, DialogHeader } from "@/components/ui/dialog";
import { Input } from "@/components/ui/form";
import { Select, optionsFromValues } from "@/components/ui/select";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { StatusBadge } from "@/components/domain/status-badge";
import { LaitSyncControls } from "@/components/domain/lait-sync";
import { CourseForm } from "@/components/domain/course-form";
import { CourseThumb } from "@/components/domain/course-image";
import { CourseDetailsDialog } from "@/components/domain/course-details-dialog";
import { UserPicker } from "@/components/domain/user-picker";
import { useSession } from "@/lib/auth/session";
import { humanise } from "@/lib/utils";

export default function CoursesPage() {
  const { permissions } = useSession();
  const { limit, offset, search, debouncedSearch, setSearch, setPage } = useListState();
  const [status, setStatus] = useState("");
  const [level, setLevel] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [tutorId, setTutorId] = useState<string | null>(null);
  const [studentId, setStudentId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [viewId, setViewId] = useState<string | null>(null);
  const router = useRouter();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["courses", "list", debouncedSearch, status, level, categoryId, tutorId, studentId, limit, offset],
    queryFn: () =>
      api.get<PageCourseSummary>("/courses", {
        query: {
          query: debouncedSearch || undefined,
          status: status || undefined,
          level: level || undefined,
          category_id: categoryId || undefined,
          tutor_id: tutorId || undefined,
          student_id: studentId || undefined,
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

  const columns: Column<CourseSummary>[] = [
    {
      key: "title",
      header: "Course",
      cell: (course) => (
        <div className="flex min-w-0 items-center gap-3">
          <CourseThumb src={course.small_course_image} title={course.title} size="md" />
          <div className="min-w-0">
            <Link href={`/courses/${course.public_id}`} className="font-medium hover:underline">
              {course.title}
            </Link>
            {course.code ? (
              <p className="font-mono text-xs text-muted-foreground">{course.code}</p>
            ) : null}
          </div>
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

  // Filtering by a person reveals who teaches and studies what, so it is offered
  // only to callers the server would allow: institution-wide access, and the
  // ability to search people at all.
  const canFilterByPerson = permissions.has("institution.view_all") && permissions.has("user.read");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Courses"
        description="The catalog. A course moves Draft -> Published -> Running -> Completed -> Archived; the server enforces which transitions are legal."
        actions={
          <>
            <LaitSyncControls
              canSync={permissions.has("course.sync")}
              runsPath="/courses/sync"
              label="Sync courses & batches"
              invalidate={[["courses"], ["batches"]]}
            />
            {permissions.has("course.create") ? (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus /> New course
              </Button>
            ) : null}
          </>
        }
      />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle p-3">
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
          <Select
            className="w-auto"
            value={(status) || null}
            aria-label="Filter by status"
            onValueChange={(next) => {
              setStatus((next ?? ""));
              setPage({ limit, offset: 0 });
            }}
           placeholder="Any status" clearable options={optionsFromValues(CourseStatusValues, humanise)} />
          <Select
            className="w-auto"
            value={(level) || null}
            aria-label="Filter by level"
            onValueChange={(next) => {
              setLevel((next ?? ""));
              setPage({ limit, offset: 0 });
            }}
           placeholder="Any level" clearable options={optionsFromValues(LevelsValues, humanise)} />
          {canReadAcademic ? (
            <>
              <Select
                className="w-auto"
                value={(categoryId) || null}
                aria-label="Filter by category"
                onValueChange={(next) => {
                  setCategoryId((next ?? ""));
                  setPage({ limit, offset: 0 });
                }}
               placeholder="Any category" clearable options={(categories.data?.items ?? []).map((category) => ({ value: category.public_id, label: category.name }))} />
            </>
          ) : null}
          {canFilterByPerson ? (
            <>
              <div className="w-52">
                <UserPicker
                  value={tutorId}
                  role="TUTOR"
                  placeholder="Any tutor"
                  onChange={(id) => {
                    setTutorId(id);
                    setPage({ limit, offset: 0 });
                  }}
                />
              </div>
              <div className="w-52">
                <UserPicker
                  value={studentId}
                  role="STUDENT"
                  placeholder="Any student"
                  onChange={(id) => {
                    setStudentId(id);
                    setPage({ limit, offset: 0 });
                  }}
                />
              </div>
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
              caption="Courses"
              columns={columns}
              rows={data?.items ?? []}
              rowKey={(course) => course.public_id}
              /*
               * A column of identical buttons is noise in a list this long, and it
               * competes with the data for the eye. The row itself opens the course;
               * the menu carries the same action for the keyboard and for touch,
               * where there is no hover to reveal anything.
               */
              onRowClick={(course) => setViewId(course.public_id)}
              rowActions={(course) => [
                {
                  label: "View details",
                  icon: <Eye className="size-4" />,
                  onSelect: () => setViewId(course.public_id),
                },
              ]}
              emptyState={
                <EmptyState
                  icon={<BookOpen />}
                  title={
                    search || status || level || categoryId
                      ? "No courses match these filters"
                      : "No courses yet"
                  }
                  description={
                    search || status || level || categoryId
                      ? "Try a different search, or clear the filters."
                      : "Create one, or sync the catalogue from LAIT."
                  }
                />
              }
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

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent size="xl">
          <DialogHeader
            title="Create a course"
            description="A new course starts in DRAFT and is invisible to students until it is published."
          />
          <CourseForm
            mode="create"
            onCancel={() => setCreateOpen(false)}
            onSaved={(course) => {
              setCreateOpen(false);
              router.push(`/courses/${course.public_id}`);
            }}
          />
        </DialogContent>
      </Dialog>

      <CourseDetailsDialog courseId={viewId} onOpenChange={(open) => !open && setViewId(null)} />
    </div>
  );
}
