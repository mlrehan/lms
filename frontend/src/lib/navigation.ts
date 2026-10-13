import type { LucideIcon } from "lucide-react";
import {
  UsersRound,
  Activity,
  BadgeCheck,
  BarChart3,
  Bell,
  BookOpen,
  Boxes,
  Building2,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  Cog,
  FileSpreadsheet,
  FolderTree,
  GraduationCap,
  KeyRound,
  LayoutDashboard,
  MessageSquare,
  Megaphone,
  MessagesSquare,
  Notebook,
  Scale,
  ScrollText,
  Share2,
  ShieldCheck,
  TrendingUp,
  Users,
  UserSquare2,
  Webhook,
  UserCog,
} from "lucide-react";
import type { PermissionName } from "@/lib/auth/permissions";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /**
   * The permission the *screen's own first request* needs. Holding it does
   * not mean every control on the page is available -- each of those is
   * gated separately, and the server checks all of them again regardless.
   *
   * `undefined` means the screen needs authentication only.
   */
  permission?: PermissionName;
  /**
   * A second permission the screen also needs, for the few screens where one
   * grant cannot separate the audiences.
   *
   * Enrollments is the case this exists for. A student holds
   * `enrollment.read` -- it is how they see their own -- so that grant alone
   * cannot tell them from a tutor. The screen is a register of *other
   * people*, and its filters are people pickers, so it also needs
   * `user.read`: every role that administers enrolments holds it and a
   * student does not.
   *
   * Deliberately a second permission rather than a role check. The console
   * gates on what a caller may do, never on what they are called, and a role
   * test here would be the first exception.
   */
  alsoRequires?: PermissionName;
  /** Shown when any one of these is held (screens with several sources). */
  anyPermission?: PermissionName[];
  description?: string;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/**
 * The console's route map.
 *
 * This is the single place a route is associated with the permission that
 * makes it usable, so the sidebar and the route guard cannot disagree about
 * who may open a page. It is navigation and UX -- `require_permissions(...)`
 * on the server is what actually protects the data.
 */
export const NAVIGATION: NavSection[] = [
  {
    label: "Overview",
    items: [
      {
        href: "/",
        label: "Dashboard",
        icon: LayoutDashboard,
        description: "Panels chosen by what you can see.",
      },
    ],
  },
  {
    label: "Learning",
    items: [
      { href: "/courses", label: "Courses", icon: BookOpen, permission: "course.read" },
      { href: "/batches", label: "Batches", icon: Boxes, permission: "batch.read" },
      { href: "/sessions", label: "Timetable", icon: CalendarDays, permission: "session.read" },
      {
        href: "/enrollments",
        label: "Enrollments",
        icon: GraduationCap,
        permission: "enrollment.read",
        // A student reaches their own enrolments through Courses and
        // Batches; this screen is everybody else's, and it was being offered
        // to them. See `alsoRequires`.
        alsoRequires: "user.read",
      },
      {
        href: "/attendance",
        label: "Attendance",
        icon: ClipboardCheck,
        permission: "attendance.read",
      },
    ],
  },
  {
    label: "Assessment",
    items: [
      {
        href: "/assignments",
        label: "Assignments",
        icon: ClipboardList,
        permission: "assignment.read",
      },
      { href: "/quizzes", label: "Quizzes", icon: Notebook, permission: "quiz.read" },
      { href: "/exams", label: "Examinations", icon: BadgeCheck, permission: "exam.read" },
      { href: "/gradebook", label: "Grade book", icon: FileSpreadsheet, permission: "grade.read" },
      // The calculation engine's own output, and the only screen that explains
      // how a mark was reached (§37). Gated on `performance.read` rather than
      // `grade.read`: a guardian and a corporate manager hold the first and not
      // the second, and explaining a result to them is the point.
      {
        href: "/performance",
        label: "Performance",
        icon: TrendingUp,
        permission: "performance.read",
      },
      { href: "/transcripts", label: "Transcripts", icon: ScrollText, permission: "grade.read" },
      // Sits with the assessment tools rather than under Settings: it is the
      // rule the marks on those screens are turned into grades by, and an
      // operator reaching for it is thinking about assessment, not about
      // system configuration.
      {
        href: "/grading-schemes",
        label: "Grading schemes",
        icon: Scale,
        permission: "grading_scheme.read",
      },
    ],
  },
  {
    label: "Content",
    items: [
      /*
       * The library -- upload, organise, share. Gated on `resource.create`
       * rather than `resource.read`, which every signed-in role holds: a
       * student reaching this screen could browse folders and open the Share
       * panel, and every control on it would answer 403 on the first click.
       * Uploading and sharing is the Super Admin's, an Administrator's and a
       * Tutor's job, and this is the permission that says so.
       *
       * What a student has instead is "Shared with me" below, which is their
       * whole relationship with resources: the files someone sent them.
       */
      { href: "/resources", label: "Resources", icon: FolderTree, permission: "resource.create" },
      { href: "/shared-with-me", label: "Shared with me", icon: Share2 },
    ],
  },
  {
    label: "Community",
    items: [
      {
        href: "/announcements",
        label: "Announcements",
        icon: Megaphone,
        permission: "announcement.read",
      },
      {
        href: "/discussions",
        label: "Discussions",
        icon: MessagesSquare,
        permission: "discussion.read",
      },
      { href: "/messages", label: "Messages", icon: MessageSquare, permission: "message.read" },
      { href: "/notifications", label: "Notifications", icon: Bell, permission: "notification.read" },
    ],
  },
  {
    label: "People",
    items: [
      { href: "/team", label: "My team", icon: UsersRound, permission: "team.read" },
      /*
       * Gated on `user.update`, not `user.read`. A Tutor, Guardian and
       * Corporate Manager all hold `user.read` -- they need it to look up the
       * people they are responsible for, and the pickers across the console
       * depend on it -- but the directory itself is an administrator's
       * screen. Reading one person is not the same as browsing everyone.
       */
      { href: "/users", label: "Users", icon: Users, permission: "user.update" },
      { href: "/roles", label: "Roles", icon: ShieldCheck, permission: "role.read" },
      { href: "/permissions", label: "Permissions", icon: KeyRound, permission: "permission.read" },
      {
        href: "/organizations",
        label: "Organizations",
        icon: Building2,
        permission: "organization.read",
      },
      { href: "/guardians", label: "Guardians", icon: UserSquare2, permission: "guardian.read" },
      // Beside Guardians, not inside Organizations: both answer "who may see
      // this student's record on their behalf", and a corporate manager's
      // roster stopped being a view of the company's payroll.
      {
        href: "/manager-links",
        label: "Manager assignments",
        icon: UserCog,
        permission: "managed_student.read",
      },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/academic", label: "Academic setup", icon: GraduationCap, permission: "academic.read" },
      { href: "/integrations", label: "Integrations", icon: Webhook, permission: "integration.read" },
      { href: "/settings", label: "System settings", icon: Cog, permission: "setting.read" },
    ],
  },
  {
    label: "Insights",
    items: [
      { href: "/reports", label: "Reports", icon: BarChart3, permission: "report.read" },
      { href: "/audit", label: "Audit log", icon: ScrollText, permission: "audit.read" },
      { href: "/security", label: "Security", icon: ShieldCheck, permission: "security.read" },
      { href: "/ops", label: "Operations", icon: Activity, permission: "setting.read" },
    ],
  },
];

/** Every route in the map, flattened -- used by the route guard. */
export const ROUTE_PERMISSIONS: { prefix: string; permission?: PermissionName }[] = NAVIGATION.flatMap(
  (section) =>
    section.items.map((item) => ({ prefix: item.href, permission: item.permission })),
)
  // Longest prefix first, so `/courses/123` matches `/courses` and not `/`.
  .sort((a, b) => b.prefix.length - a.prefix.length);

export function permissionForPath(pathname: string): PermissionName | undefined {
  for (const route of ROUTE_PERMISSIONS) {
    if (route.prefix === "/") continue;
    if (pathname === route.prefix || pathname.startsWith(`${route.prefix}/`)) {
      return route.permission;
    }
  }
  return undefined;
}
