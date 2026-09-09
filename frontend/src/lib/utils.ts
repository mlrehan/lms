import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Title-case a snake/kebab/dotted token for display, e.g. `LOGIN_FAILED`. */
export function humanise(value: string): string {
  return value
    .replace(/[._-]+/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** `a.b` -> `a`. Used to group permissions and audit actions by module. */
export function moduleOf(permission: string): string {
  const [head] = permission.split(".");
  return head ?? permission;
}

/** `a.b` -> `b`. */
export function actionOf(permission: string): string {
  const parts = permission.split(".");
  return parts.length > 1 ? parts.slice(1).join(".") : permission;
}
