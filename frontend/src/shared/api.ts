// One way to call the backend from both apps. The session cookie is sent automatically (same address).
// Errors come back as {"error": {"code", "message"}} (older routes: {"detail": {"error": ...}}).

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = data.error ?? data.detail?.error ?? {};
    throw new ApiError(response.status, error.code ?? "error", error.message ?? `Request failed (${response.status}).`);
  }
  return data as T;
}

export type Me = { email: string; role: "admin" | "tester"; status: "pending" | "approved" | "rejected"; tokens: number };
