/**
 * Effective-permission checks.
 *
 * **The backend is the authorization layer.** Everything here exists so the
 * console does not offer a person a button that will fail, and so a route
 * they cannot use redirects instead of rendering an error. It is UX and
 * navigation, nothing more: hiding a control does not protect anything, and
 * every one of these checks is repeated -- authoritatively -- by
 * `require_permissions(...)` on the server for the request the control would
 * have sent.
 *
 * The permission set comes from `GET /auth/me`, which returns the caller's
 * *effective* permissions after role resolution. Nothing in this console
 * derives capability from a role name: an institution that adds a REGISTRAR
 * role with `institution.view_all` and no write rights must not need a
 * frontend change, and `role === "ADMIN"` cannot express that.
 */

import type { PermissionName } from "./permission-names";

export type { PermissionName };
export { PERMISSION_NAMES, PERMISSION_DESCRIPTIONS } from "./permission-names";

export interface PermissionSet {
  has(permission: PermissionName): boolean;
  hasAny(...permissions: PermissionName[]): boolean;
  hasAll(...permissions: PermissionName[]): boolean;
  /** The raw list, for the "what can I do?" screen. */
  readonly all: readonly string[];
}

export function permissionSet(granted: readonly string[] | undefined): PermissionSet {
  const set = new Set(granted ?? []);
  return {
    all: granted ?? [],
    has: (permission) => set.has(permission),
    hasAny: (...permissions) => permissions.some((p) => set.has(p)),
    hasAll: (...permissions) => permissions.every((p) => set.has(p)),
  };
}

/**
 * `institution.view_all` is the scope modifier, not a capability: it widens
 * *which rows* a caller sees rather than what they may do. Screens that show
 * "everyone's" data versus "mine" branch on this.
 */
export const VIEW_ALL: PermissionName = "institution.view_all";
