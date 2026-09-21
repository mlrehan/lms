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
  ScrollText,
  Share2,
  ShieldCheck,
  Users,
  UserSquare2,
  Webhook,
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
      { href: "/transcripts", label: "Transcripts", icon: ScrollText, permission: "grade.read" },
    ],
  },
  {
    label: "Content",
    items: [
      { href: "/resources", label: "Resources", icon: FolderTree, permission: "resource.read" },
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
      { href: "/users", label: "Users", icon: Users, permission: "user.read" },
      { href: "/roles", label: "Roles", icon: ShieldCheck, permission: "role.read" },
      { href: "/permissions", label: "Permissions", icon: KeyRound, permission: "permission.read" },
      {
        href: "/organizations",
        label: "Organizations",
        icon: Building2,
        permission: "organization.read",
      },
      { href: "/guardians", label: "Guardians", icon: UserSquare2, permission: "guardian.read" },
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
