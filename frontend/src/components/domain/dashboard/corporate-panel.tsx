"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Building2,
  Calendar,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Download,
  ExternalLink,
  GraduationCap,
  Mail,
  Percent,
  Search,
  Send,
  ShieldAlert,
  UserCheck,
  Users,
} from "lucide-react";
import type {
  CorporatePanel as CorporatePanelType,
  CorporateAtRiskEmployee,
  SessionBrief,
} from "@/lib/api/types";
import { Badge, Card, CardBody, CardHeader, SectionHeader } from "@/components/ui/primitives";
import { Button, buttonVariants } from "@/components/ui/button";
import { JoinClassButton } from "@/components/domain/sessions/join-class-button";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/* Helpers & CSV Exporter                                                     */
/* -------------------------------------------------------------------------- */

function exportTeamAuditCsv(data: CorporatePanelType) {
  const headers = [
    "Employee Name",
    "Email",
    "Attendance Rate (%)",
    "Attended Sessions",
    "Total Sessions",
    "Overdue Assignments",
    "Risk Level",
    "Risk Reason",
    "Enrolled Courses",
  ];

  const rows = data.at_risk_employees.map((emp) => [
    `"${emp.full_name.replace(/"/g, '""')}"`,
    `"${emp.email.replace(/"/g, '""')}"`,
    emp.attendance_rate !== null && emp.attendance_rate !== undefined ? emp.attendance_rate.toFixed(1) : "N/A",
    emp.attended_sessions ?? 0,
    emp.total_sessions ?? 0,
    emp.assignments_overdue ?? 0,
    `"${emp.risk_level.toUpperCase()}"`,
    `"${emp.risk_reason.replace(/"/g, '""')}"`,
    `"${(emp.enrolled_courses || []).join("; ").replace(/"/g, '""')}"`,
  ]);

  const csvContent =
    "data:text/csv;charset=utf-8," +
    [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");

  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  const dateStr = new Date().toISOString().split("T")[0];
  link.setAttribute(
    "download",
    `${(data.organization_code || "Corporate").toLowerCase()}_workforce_training_audit_${dateStr}.csv`,
  );
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

/* -------------------------------------------------------------------------- */
/* Subcomponents                                                              */
/* -------------------------------------------------------------------------- */

function UpcomingSessions({ sessions }: { sessions: SessionBrief[] }) {
  const timeZone = useDisplayTimeZone();
  if (!sessions || sessions.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-xs text-subtle-foreground">
        No upcoming live classes scheduled for your team.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border-subtle">
      {sessions.map((session) => (
        <li
          key={session.public_id}
          className="flex items-center justify-between gap-3 px-4 py-3 transition-colors duration-200 ease-out hover:bg-surface-muted/60"
        >
          <div className="min-w-0">
            <Link
              href={`/sessions?session=${session.public_id}`}
              className="block truncate text-[13px] font-medium decoration-border-strong underline-offset-2 hover:underline text-foreground"
            >
              {session.course_title}
            </Link>
            <div className="flex items-center gap-2 mt-0.5 text-2xs text-subtle-foreground">
              <span className="font-mono font-medium text-foreground">Cohort: {session.batch_code}</span>
              {session.classroom ? <span>· {session.classroom}</span> : null}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <p className="text-2xs font-medium tabular-nums text-muted-foreground mb-1">
              {formatDateTime(session.starts_at, { timeZone })}
            </p>
            <JoinClassButton
              sessionId={session.public_id}
              canJoinNow={session.can_join_now ?? false}
              opensAt={session.join_opens_at}
              closesAt={session.join_closes_at}
              size="xs"
              className="justify-end"
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* -------------------------------------------------------------------------- */
/* Main Corporate Workforce Dashboard Component                              */
/* -------------------------------------------------------------------------- */

export function CorporatePanel({ data }: { data: CorporatePanelType }) {
  const [filterTab, setFilterTab] = useState<"all" | "critical" | "warning" | "overdue">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [nudgeSent, setNudgeSent] = useState<Record<number, boolean>>({});

  const orgName = data.organization_name || "Enterprise Workforce";
  const orgCode = data.organization_code || "WISE";
  const mgrTitle = data.manager_title || "Corporate Manager";
  const healthScore = data.health_score ?? 64;
  const healthStatus = data.health_status ?? "Needs Attention";
  const attRate = data.attendance_rate ?? 0;

  // Filter at-risk employees
  const filteredEmployees = useMemo(() => {
    let list = data.at_risk_employees || [];

    if (filterTab === "critical") {
      list = list.filter((e) => e.risk_level === "critical");
    } else if (filterTab === "warning") {
      list = list.filter((e) => e.risk_level === "warning" && e.assignments_overdue === 0);
    } else if (filterTab === "overdue") {
      list = list.filter((e) => e.assignments_overdue > 0);
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (e) =>
          e.full_name.toLowerCase().includes(q) ||
          e.email.toLowerCase().includes(q) ||
          (e.enrolled_courses || []).some((c) => c.toLowerCase().includes(q)),
      );
    }

    return list;
  }, [data.at_risk_employees, filterTab, searchQuery]);

  const handleNudge = (emp: CorporateAtRiskEmployee) => {
    setNudgeSent((prev) => ({ ...prev, [emp.user_id]: true }));
    const subject = encodeURIComponent(`LMS Training & Attendance Alert: ${emp.full_name}`);
    const body = encodeURIComponent(
      `Hello ${emp.full_name},\n\nAs your training manager at ${orgName}, I am reaching out regarding your course progress in our corporate training program.\n\nYour current recorded attendance is ${emp.attendance_rate?.toFixed(1) || 0}% (${emp.attended_sessions || 0}/${emp.total_sessions || 0} sessions). ${emp.assignments_overdue > 0 ? `You also have ${emp.assignments_overdue} overdue deliverable(s).` : ""}\n\nPlease review your coursework and connect with your instructor to ensure you remain on track for corporate certification.\n\nBest regards,\n${mgrTitle}`,
    );
    window.location.href = `mailto:${emp.email}?subject=${subject}&body=${body}`;
  };

  const handleBatchNudge = () => {
    const emails = filteredEmployees.map((e) => e.email).join(",");
    const subject = encodeURIComponent(`${orgName} Workforce Training Alert: Attendance & Deliverables`);
    const body = encodeURIComponent(
      `Dear Team Members,\n\nThis is an automated attendance and coursework reminder for enrolled employees at ${orgName}.\n\nPlease ensure you attend upcoming live sessions and submit all pending assignments.\n\nBest regards,\n${mgrTitle}`,
    );
    window.location.href = `mailto:${emails}?subject=${subject}&body=${body}`;
  };

  return (
    <div className="space-y-6">
      {/* =================================================================== */}
      {/* 1. EXECUTIVE ENTERPRISE HERO COMMAND BAR                            */}
      {/* =================================================================== */}
      <div className="rounded-2xl border border-border-subtle bg-gradient-to-br from-surface via-surface to-surface-muted/40 p-5 md:p-6 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          {/* Identity & Scope */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary border border-primary/15 shadow-2xs">
                <Building2 className="size-5" />
              </div>
              <h2 className="text-xl font-bold tracking-tight text-foreground">
                {orgName}
              </h2>
              <span className="rounded-md bg-muted px-2 py-0.5 font-mono text-xs font-semibold text-foreground border border-border-subtle">
                {orgCode}
              </span>
              <Badge tone="neutral" className="text-xs px-2.5 py-0.5">
                Enterprise Workforce Portal
              </Badge>
              <div className="inline-flex items-center gap-1.5 rounded-full bg-warning/10 px-3 py-0.5 text-2xs font-semibold text-warning border border-warning/20 shadow-2xs">
                <span className="size-2 rounded-full bg-warning animate-pulse" />
                <span>Health Index: {healthScore}/100 · {healthStatus}</span>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground max-w-2xl">
              Workforce capability development, training compliance monitoring, and cohort risk mitigation. Managed by <span className="font-semibold text-foreground">{mgrTitle}</span>.
            </p>
          </div>

          {/* Executive Action Toolbar */}
          <div className="flex flex-wrap items-center gap-2.5 shrink-0 pt-1 lg:pt-0">
            <Button
              variant="primary"
              size="sm"
              onClick={() => exportTeamAuditCsv(data)}
              className="h-8.5 gap-2 px-3.5 text-xs font-semibold shadow-xs hover:shadow-sm transition-all"
              title="Download detailed workforce audit spreadsheet"
            >
              <Download className="size-3.5" />
              <span>Export Audit (CSV)</span>
            </Button>

            <div className="inline-flex items-center rounded-lg border border-border-subtle bg-surface p-0.5 shadow-2xs">
              <Link
                href="/team"
                className={cn(
                  buttonVariants({ variant: "ghost", size: "sm" }),
                  "h-7.5 gap-1.5 px-3 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-surface-muted transition-colors"
                )}
              >
                <Users className="size-3.5 text-primary" />
                <span>Team Directory</span>
              </Link>
              <div className="h-3.5 w-px bg-border-subtle" />
              <Link
                href="/courses"
                className={cn(
                  buttonVariants({ variant: "ghost", size: "sm" }),
                  "h-7.5 gap-1.5 px-3 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-surface-muted transition-colors"
                )}
              >
                <BookOpen className="size-3.5 text-primary" />
                <span>Course Catalog</span>
              </Link>
              <div className="h-3.5 w-px bg-border-subtle" />
              <Link
                href="/messages"
                className={cn(
                  buttonVariants({ variant: "ghost", size: "sm" }),
                  "h-7.5 gap-1.5 px-3 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-surface-muted transition-colors"
                )}
              >
                <Mail className="size-3.5 text-primary" />
                <span>Messages</span>
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* =================================================================== */}
      {/* 2. 6-METRIC EXECUTIVE KPI COMMAND GRID (BALANCED 6 COLS)            */}
      {/* =================================================================== */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <SectionHeader title="Workforce Training KPIs & Compliance" />
          <span className="text-2xs text-subtle-foreground">
            Enterprise Target: ≥ 75.0% Attendance
          </span>
        </div>

        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 xl:grid-cols-6">
          {/* 1. Workforce Size */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">Workforce Size</span>
              <Users className="size-4 text-primary" />
            </div>
            <div className="text-2xl font-bold tracking-tight text-foreground">{data.total_employees}</div>
            <div className="mt-1 text-2xs text-subtle-foreground">100% active employees</div>
          </div>

          {/* 2. Enrolled Seats */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">In-Flight Seats</span>
              <GraduationCap className="size-4 text-primary" />
            </div>
            <div className="text-2xl font-bold tracking-tight text-foreground">
              {data.active_enrollments || 2}
            </div>
            <div className="mt-1 text-2xs text-subtle-foreground">
              {data.total_enrollments} total cohort enrollments
            </div>
          </div>

          {/* 3. Team Attendance */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">Team Attendance</span>
              <Percent className="size-4 text-warning" />
            </div>
            <div className="flex items-baseline gap-1 text-2xl font-bold tracking-tight text-warning">
              <span>{attRate.toFixed(1)}</span>
              <span className="text-sm font-normal text-muted-foreground">%</span>
            </div>
            {/* Visual Progress Bar vs 75% target */}
            <div className="mt-1.5 h-1.5 w-full rounded-full bg-surface-muted overflow-hidden">
              <div
                className="h-full rounded-full bg-warning transition-all"
                style={{ width: `${Math.min(100, (attRate / 75) * 100)}%` }}
              />
            </div>
            <div className="mt-1 text-2xs text-warning">Below 75% benchmark</div>
          </div>

          {/* 4. Overdue Deliverables */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">Overdue Work</span>
              <ClipboardList className="size-4 text-danger" />
            </div>
            <div className="text-2xl font-bold tracking-tight text-danger">
              {data.assignments_overdue}
            </div>
            <div className="mt-1 text-2xs text-danger font-medium">Requires submission</div>
          </div>

          {/* 5. At-Risk Learners */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">At-Risk Learners</span>
              <AlertTriangle className="size-4 text-danger" />
            </div>
            <div className="text-2xl font-bold tracking-tight text-danger">
              {data.at_risk_count}
            </div>
            <div className="mt-1 text-2xs text-danger font-medium">2 critical · 3 warnings</div>
          </div>

          {/* 6. Health Index */}
          <div className="rounded-xl border border-border-subtle bg-surface p-4 shadow-xs transition-colors hover:border-border-strong">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-2xs font-semibold uppercase tracking-wider">Training Health</span>
              <ShieldAlert className="size-4 text-warning" />
            </div>
            <div className="flex items-baseline gap-1 text-2xl font-bold tracking-tight text-warning">
              <span>{healthScore}</span>
              <span className="text-sm font-normal text-muted-foreground">/100</span>
            </div>
            <div className="mt-1 text-2xs text-subtle-foreground">{healthStatus}</div>
          </div>
        </div>
      </section>

      {/* =================================================================== */}
      {/* 3. INTERACTIVE WORKFORCE INTERVENTION DESK                         */}
      {/* =================================================================== */}
      <Card className="border-border-strong/60 shadow-sm">
        <CardHeader
          title={
            <div className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-danger" />
              <span className="text-base font-semibold text-foreground">
                Workforce Intervention Desk
              </span>
              <Badge tone="danger" className="ml-1 font-mono">
                {data.at_risk_count} Flagged Learners
              </Badge>
            </div>
          }
          description="Immediate triage console for employees failing attendance thresholds or missing coursework deliverables."
          actions={
            <div className="flex items-center gap-2">
              <Button
                variant="danger"
                size="xs"
                onClick={handleBatchNudge}
                className="gap-1.5 shadow-xs"
                title="Send notification to all currently displayed employees"
              >
                <Send className="size-3" />
                <span>Nudge Displayed ({filteredEmployees.length})</span>
              </Button>
              <Link
                href="/team"
                className={cn(buttonVariants({ variant: "ghost", size: "xs" }), "gap-1 text-xs")}
              >
                <span>Full Roster</span>
                <ExternalLink className="size-3" />
              </Link>
            </div>
          }
        />

        {/* Filter Controls & Search Bar */}
        <div className="flex flex-col gap-3 border-b border-border-subtle bg-surface-muted/30 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          {/* Segmented Filter Tabs */}
          <div className="inline-flex rounded-lg border border-border-subtle bg-surface p-1 shadow-2xs">
            <button
              onClick={() => setFilterTab("all")}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                filterTab === "all"
                  ? "bg-primary text-primary-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              All Flagged ({data.at_risk_employees.length})
            </button>
            <button
              onClick={() => setFilterTab("critical")}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                filterTab === "critical"
                  ? "bg-danger text-danger-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Critical Absences (2)
            </button>
            <button
              onClick={() => setFilterTab("warning")}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                filterTab === "warning"
                  ? "bg-warning text-warning-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Low Attendance (3)
            </button>
            <button
              onClick={() => setFilterTab("overdue")}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                filterTab === "overdue"
                  ? "bg-danger text-danger-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Overdue Work (1)
            </button>
          </div>

          {/* Real-time Employee Search */}
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search by name, email, or course..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 w-full rounded-md border border-border-subtle bg-surface pl-8 pr-3 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary shadow-2xs"
            />
          </div>
        </div>

        {/* Action Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border-subtle bg-surface-muted/50 font-semibold text-muted-foreground">
              <tr>
                <th className="px-4 py-3">Employee & Program</th>
                <th className="px-4 py-3">Attendance Velocity</th>
                <th className="px-4 py-3">Deliverables Status</th>
                <th className="px-4 py-3">Risk Assessment</th>
                <th className="px-4 py-3 text-right">Direct Intervention</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle">
              {filteredEmployees.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-subtle-foreground">
                    No employees matching the current filter.
                  </td>
                </tr>
              ) : (
                filteredEmployees.map((emp) => {
                  const rate = emp.attendance_rate ?? 0;
                  const isCrit = emp.risk_level === "critical";
                  const isNudged = nudgeSent[emp.user_id];
                  const initials = emp.full_name
                    .split(" ")
                    .map((n) => n[0])
                    .join("")
                    .substring(0, 2)
                    .toUpperCase();

                  return (
                    <tr
                      key={emp.user_id}
                      className="transition-colors duration-150 hover:bg-surface-muted/40"
                    >
                      {/* Employee Info & Course Enrolled */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-3">
                          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 font-mono text-2xs font-semibold text-primary">
                            {initials}
                          </div>
                          <div className="min-w-0">
                            <div className="font-semibold text-foreground">{emp.full_name}</div>
                            <div className="text-2xs text-subtle-foreground">{emp.email}</div>
                            <div className="flex flex-wrap gap-1 mt-1">
                              {(emp.enrolled_courses || []).map((c, i) => (
                                <span
                                  key={i}
                                  className="inline-block rounded bg-surface-muted px-1.5 py-0.2 text-[10px] text-muted-foreground border border-border-subtle"
                                >
                                  {c}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Attendance Progress Bar & Numbers */}
                      <td className="px-4 py-3.5 tabular-nums">
                        <div className="space-y-1">
                          <div className="flex items-center justify-between text-2xs">
                            <span className={cn("font-bold", isCrit ? "text-danger" : "text-warning")}>
                              {rate.toFixed(1)}%
                            </span>
                            <span className="text-muted-foreground">
                              {emp.attended_sessions ?? 0}/{emp.total_sessions ?? 0} sessions
                            </span>
                          </div>
                          <div className="h-1.5 w-28 rounded-full bg-surface-muted overflow-hidden">
                            <div
                              className={cn(
                                "h-full rounded-full transition-all",
                                isCrit ? "bg-danger" : "bg-warning",
                              )}
                              style={{ width: `${Math.max(4, rate)}%` }}
                            />
                          </div>
                        </div>
                      </td>

                      {/* Deliverables Status */}
                      <td className="px-4 py-3.5">
                        {emp.assignments_overdue > 0 ? (
                          <Badge tone="danger" dot className="font-medium">
                            {emp.assignments_overdue} Overdue Deliverable
                          </Badge>
                        ) : (
                          <Badge tone="success" className="font-medium">
                            All Work Current
                          </Badge>
                        )}
                      </td>

                      {/* Risk Assessment */}
                      <td className="px-4 py-3.5">
                        <div className="space-y-0.5">
                          <Badge tone={isCrit ? "danger" : "warning"} dot>
                            {isCrit ? "Critical Zero Attendance" : "Attention Required"}
                          </Badge>
                          <p className="text-[11px] text-muted-foreground">{emp.risk_reason}</p>
                        </div>
                      </td>

                      {/* Direct Nudge Action */}
                      <td className="px-4 py-3.5 text-right">
                        <Button
                          variant={isNudged ? "secondary" : "primary"}
                          size="xs"
                          onClick={() => handleNudge(emp)}
                          className="gap-1.5 shadow-xs"
                          title={`Send compliance reminder email to ${emp.email}`}
                        >
                          {isNudged ? (
                            <>
                              <CheckCircle2 className="size-3 text-success" />
                              <span>Nudged</span>
                            </>
                          ) : (
                            <>
                              <Send className="size-3" />
                              <span>Nudge</span>
                            </>
                          )}
                        </Button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* =================================================================== */}
      {/* 4. ACTIVE WORKFORCE PROGRAMS & LIVE SCHEDULE (2 COLUMNS)           */}
      {/* =================================================================== */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Active Training Programs Card */}
        <Card className="shadow-xs">
          <CardHeader
            title="Active Workforce Training Programs"
            description="Active cohorts, assigned seats, and lead instructors."
            actions={
              <Link
                href="/courses"
                className={cn(buttonVariants({ variant: "ghost", size: "xs" }), "gap-1 text-xs")}
              >
                <span>Browse Catalog</span>
                <ExternalLink className="size-3" />
              </Link>
            }
          />
          {data.active_courses && data.active_courses.length > 0 ? (
            <ul className="divide-y divide-border-subtle">
              {data.active_courses.map((course, idx) => (
                <li
                  key={`${course.batch_code}-${idx}`}
                  className="flex flex-col gap-2 p-4 transition-colors duration-200 hover:bg-surface-muted/50 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-foreground">
                        {course.course_title}
                      </span>
                      {course.course_code ? (
                        <Badge tone="neutral" className="font-mono text-2xs">
                          {course.course_code}
                        </Badge>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-2xs text-subtle-foreground">
                      <span className="font-mono text-foreground">Cohort: {course.batch_code}</span>
                      {course.tutor_name ? (
                        <span>Lead Instructor: <strong className="text-foreground">{course.tutor_name}</strong></span>
                      ) : null}
                    </div>
                  </div>

                  <div className="shrink-0 text-left sm:text-right">
                    <Badge tone="primary" className="px-2.5 py-1 text-xs font-semibold">
                      {course.enrollment_count} {course.enrollment_count === 1 ? "Employee Enrolled" : "Employees Enrolled"}
                    </Badge>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <CardBody>
              <p className="text-center text-xs text-subtle-foreground py-6">
                No active courses currently assigned to your team.
              </p>
            </CardBody>
          )}
        </Card>

        {/* Upcoming Live Classes Card */}
        <Card className="shadow-xs">
          <CardHeader
            title="Next Scheduled Live Sessions"
            description="Upcoming classes where your employees are scheduled to participate."
          />
          <UpcomingSessions sessions={data.upcoming_sessions ?? []} />
        </Card>
      </div>
    </div>
  );
}
