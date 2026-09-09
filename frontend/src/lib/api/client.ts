/**
 * The browser-side API client. Everything goes to `/api/backend/...`, the
 * same-origin proxy -- there is no code path from the browser to the LMS API
 * directly, and no token to attach if there were.
 */

export interface ApiErrorPayload {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message?.trim() || defaultMessage(status));
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code ?? "UNKNOWN";
    this.details = payload.details ?? {};
  }

  /** The session ended or was never established. */
  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  /** Authenticated, but not permitted. The backend is the authority here. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /**
   * Per-field validation messages, when the backend supplied them, so a form
   * can point at the offending input instead of showing a banner.
   */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(this.details)) {
      if (typeof value === "string") out[key] = value;
      else if (Array.isArray(value) && typeof value[0] === "string") out[key] = value[0];
    }
    return out;
  }
}

function defaultMessage(status: number): string {
  if (status === 401) return "Your session has ended. Please sign in again.";
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) return "That record could not be found.";
  if (status === 409) return "That conflicts with something that already exists.";
  if (status === 429) return "Too many requests. Please wait a moment and try again.";
  if (status >= 500) return "The server could not complete that request.";
  return "The request could not be completed.";
}

export interface RequestOptions {
  query?: QueryParams;
  signal?: AbortSignal;
  /** Sent as-is for `FormData`; JSON-encoded otherwise. */
  body?: unknown;
}

export type QueryValue = string | number | boolean | null | undefined | (string | number)[];
export type QueryParams = Record<string, QueryValue>;

export function buildQuery(params: QueryParams | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

/**
 * Path segments are encoded individually. Ids come from API responses today,
 * but a screen that ever interpolates user input into a path must not be able
 * to escape the segment it was given.
 */
export function segment(value: string | number): string {
  return encodeURIComponent(String(value));
}

const BASE = "/api/backend";

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  let body: BodyInit | undefined;

  if (options.body instanceof FormData) {
    // No content-type: the browser must set the multipart boundary itself.
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`${BASE}${path}${buildQuery(options.query)}`, {
    method,
    headers,
    body,
    signal: options.signal,
    credentials: "same-origin",
  });

  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");

  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    if (isJson) {
      try {
        payload = (await response.json()) as ApiErrorPayload;
      } catch {
        payload = {};
      }
    }
    throw new ApiError(response.status, payload);
  }

  if (!isJson) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>("GET", path, options),
  post: <T>(path: string, options?: RequestOptions) => request<T>("POST", path, options),
  put: <T>(path: string, options?: RequestOptions) => request<T>("PUT", path, options),
  patch: <T>(path: string, options?: RequestOptions) => request<T>("PATCH", path, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};

/**
 * A download that must carry the caller's credentials, so it cannot be a
 * plain `<a href>` to the API. Fetches through the proxy and hands the blob
 * to the browser.
 */
export async function downloadFile(
  path: string,
  fallbackName: string,
  query?: QueryParams,
): Promise<void> {
  const response = await fetch(`${BASE}${path}${buildQuery(query)}`, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    let payload: ApiErrorPayload = {};
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      payload = {};
    }
    throw new ApiError(response.status, payload);
  }

  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const name = match?.[1] ? decodeURIComponent(match[1]) : fallbackName;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
