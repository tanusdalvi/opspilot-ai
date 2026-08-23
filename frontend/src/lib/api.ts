/** Typed fetch wrapper: session header management + safe error shape. */

const BASE = "";
const SESSION_STORAGE_KEY = "opspilot.session";

/**
 * Session token survives page reloads via sessionStorage (per-tab, cleared
 * when the browser tab closes). Backend sessions are process-local, so a
 * stale token simply mints a fresh session server-side — never an error.
 */
let sessionToken: string | null = (() => {
  try {
    return sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
})();

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function adoptSession(response: Response): void {
  const header = response.headers.get("X-OpsPilot-Session");
  if (header && header !== sessionToken) {
    sessionToken = header;
    try {
      sessionStorage.setItem(SESSION_STORAGE_KEY, header);
    } catch {
      /* persistence is best-effort */
    }
  }
}

async function parseError(response: Response): Promise<never> {
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    message = body.error ?? body.detail ?? message;
    if (typeof message !== "string") message = JSON.stringify(message);
  } catch {
    /* keep default */
  }
  throw new ApiError(response.status, message);
}

export async function api<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const { json, ...rest } = init ?? {};
  const response = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(sessionToken ? { "X-OpsPilot-Session": sessionToken } : {}),
      ...(rest.headers ?? {}),
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  adoptSession(response);
  if (!response.ok) return parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(path, {
    method: "POST",
    headers: sessionToken ? { "X-OpsPilot-Session": sessionToken } : {},
    body: form,
  });
  adoptSession(response);
  if (!response.ok) return parseError(response);
  return (await response.json()) as T;
}
