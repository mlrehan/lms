/**
 * Server-only configuration.
 *
 * Read through a function rather than a module-level constant so a missing
 * value fails on the request that needs it, with a message naming the
 * variable -- not at import time, where Next would surface it as an opaque
 * build error in a file that has nothing to do with configuration.
 */

export function apiBaseUrl(): string {
  const value = process.env.LMS_API_URL;
  if (!value) {
    throw new Error(
      "LMS_API_URL is not set. Point it at the LMS API, e.g. " +
        "http://127.0.0.1:8000/api/v1 (see .env.example).",
    );
  }
  return value.replace(/\/+$/, "");
}

export const isProduction = process.env.NODE_ENV === "production";
