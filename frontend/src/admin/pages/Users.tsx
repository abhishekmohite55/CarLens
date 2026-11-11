import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../shared/api";
import { Badge, Button, td, th, useLoad, when } from "../ui";

type User = {
  id: number; email: string; role: string; status: string; tokens: number; has_password: boolean; google: boolean;
  locked: boolean; runs: number; sessions: number; created_at: string; last_login_at: string | null;
};
const FILTERS = ["pending", "approved", "rejected", ""] as const;

export function Users() {
  const [status, setStatus] = useState<(typeof FILTERS)[number]>("pending");
  const load = useCallback(() => api<{ users: User[] }>(`/api/admin/users${status ? `?status=${status}` : ""}`), [status]);
  const { data, error, act } = useLoad(load);
  const post = (path: string, body?: unknown) => api(path, { method: "POST", body });

  function resetPassword(user: User) {
    const password = window.prompt(`New password for ${user.email} (at least 10 characters). They are signed out everywhere.`);
    if (password) act(() => post(`/api/admin/users/${user.id}/password`, { password }));
  }
  function setTokens(user: User) {
    const value = window.prompt(`Tokens for ${user.email}`, String(user.tokens));
    if (value !== null && value.trim() !== "") act(() => api(`/api/admin/users/${user.id}/tokens`, { method: "PATCH", body: { set: Number(value) } }));
  }
  // − / + change the number on screen at once; it is saved 1 s after the last click, as one change and one
  // audit row (owner, 12 Nov; no "saving…" text: it moved the buttons). Leaving the page saves what is still waiting.
  const [pending, setPending] = useState<Record<number, number>>({});
  const timers = useRef<Record<number, number>>({});
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  const saveTokens = useCallback((userId: number) => {
    const value = pendingRef.current[userId];
    delete timers.current[userId];
    if (value === undefined) return;
    act(async () => {
      await api(`/api/admin/users/${userId}/tokens`, { method: "PATCH", body: { set: value } });
      setPending((p) => { const next = { ...p }; delete next[userId]; return next; });
    });
  }, [act]);

  function addTokens(user: User, add: number) {
    const current = pending[user.id] ?? user.tokens;
    setPending((p) => ({ ...p, [user.id]: Math.max(0, current + add) }));
    window.clearTimeout(timers.current[user.id]);
    timers.current[user.id] = window.setTimeout(() => saveTokens(user.id), 1000);
  }

  useEffect(() => {
    const flush = () => Object.keys(timers.current).forEach((id) => {
      window.clearTimeout(timers.current[Number(id)]);
      const value = pendingRef.current[Number(id)];
      // keepalive lets the request finish while the page closes
      if (value !== undefined) fetch(`/api/admin/users/${id}/tokens`, { method: "PATCH", keepalive: true,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ set: value }) });
    });
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, []);
  function remove(user: User) {
    if (window.confirm(`Delete ${user.email}? This cannot be undone.`)) act(() => api(`/api/admin/users/${user.id}`, { method: "DELETE" }));
  }

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Users & requests</h1>
      <div className="mb-4 flex gap-2">
        {FILTERS.map((f) => (
          <button key={f || "all"} onClick={() => setStatus(f)}
            className={`rounded px-3 py-1 text-sm ${status === f ? "bg-neutral-700 text-white" : "bg-neutral-900 text-neutral-400"}`}>
            {f || "all"}
          </button>
        ))}
      </div>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
      <table className="w-full">
        <thead>
          <tr>{["Email", "Sign-in", "Status", "Tokens", "Runs", "Last sign-in", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data?.users.map((u) => (
            <tr key={u.id}>
              <td className={td}>{u.email}{u.locked && <span className="ml-2 text-xs text-amber-400">locked</span>}</td>
              <td className={td}>{[u.google && "Google", u.has_password && "password"].filter(Boolean).join(" + ")}</td>
              <td className={td}><Badge text={u.role === "admin" ? "admin" : u.status} /></td>
              <td className={td}>
                {u.role === "admin" ? "—" : (
                  <span className="flex items-center gap-1">
                    <Button onClick={() => addTokens(u, -1)} disabled={(pending[u.id] ?? u.tokens) === 0}>−</Button>
                    <button onClick={() => setTokens(u)} className="w-8 text-center hover:underline">{pending[u.id] ?? u.tokens}</button>
                    <Button onClick={() => addTokens(u, 1)}>+</Button>
                  </span>
                )}
              </td>
              <td className={td}>{u.runs}</td>
              <td className={td}>{when(u.last_login_at)}</td>
              <td className={td}>
                {u.role !== "admin" && (
                  <span className="flex flex-wrap gap-1">
                    {u.status !== "approved" && <Button kind="primary" onClick={() => act(() => post(`/api/admin/users/${u.id}/approve`))}>Approve</Button>}
                    {u.status !== "rejected" && <Button onClick={() => act(() => post(`/api/admin/users/${u.id}/reject`))}>Reject</Button>}
                    <Button onClick={() => resetPassword(u)}>Reset password</Button>
                    {u.sessions > 0 && <Button onClick={() => act(() => post(`/api/admin/users/${u.id}/signout`))}>Sign out</Button>}
                    {u.runs === 0 && <Button kind="danger" onClick={() => remove(u)}>Delete</Button>}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.users.length === 0 && <p className="mt-4 text-sm text-neutral-500">Nobody here.</p>}
    </div>
  );
}
