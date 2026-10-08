// Thin fetch wrapper around the GrowthOS API. All requests carry the JWT; errors become ApiError.
const BASE = import.meta.env.VITE_API_URL ?? "/api";
const TOKEN_KEY = "growthos_token";

export class ApiError extends Error {
  constructor(public status: number, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}

export const auth = {
  get token() {
    return localStorage.getItem(TOKEN_KEY);
  },
  set(token: string) {
    localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
  },
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the GrowthOS API. Is the backend running?");
  }
  if (response.status === 401 && auth.token) {
    auth.clear();
    window.location.href = "/login";
  }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const err = data?.error;
    const message = err?.message ?? data?.detail ?? `Request failed (${response.status})`;
    throw new ApiError(response.status, typeof message === "string" ? message : "Request failed", err?.details ?? {});
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const reasons = err.details?.reasons as string[] | undefined;
    if (reasons?.length) return `${err.message} Reasons: ${reasons.map((r) => r.replace(/_/g, " ")).join(", ")}.`;
    const fields = err.details?.fields as { field: string; message: string }[] | undefined;
    if (fields?.length) return `${err.message}: ${fields.map((f) => `${f.field} – ${f.message}`).join("; ")}`;
    return err.message;
  }
  return "Unexpected error";
}
