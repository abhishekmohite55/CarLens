import { useState, type FormEvent } from "react";
import { api, ApiError, type Me } from "./api";

/** Email + password; asks for the authenticator code when the backend says code_required (admin). */
export function SignIn({ title, onSignedIn }: { title: string; onSignedIn: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      onSignedIn(await api<Me>("/api/auth/login", { method: "POST", body: { email, password, code: code || null } }));
    } catch (e) {
      if (e instanceof ApiError && e.code === "code_required") setNeedCode(true);
      setError(e instanceof Error ? e.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-neutral-100 outline-none focus:border-blue-500";
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 text-neutral-200">
      <form onSubmit={submit} className="w-80 space-y-3">
        <h1 className="text-xl font-semibold">{title}</h1>
        <label className="block text-sm text-neutral-400">
          Email
          <input className={input} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm text-neutral-400">
          Password
          <input className={input} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {needCode && (
          <label className="block text-sm text-neutral-400">
            Authenticator code
            <input className={input} inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
        )}
        <button disabled={busy} className="w-full rounded bg-blue-600 py-2 font-medium text-white hover:bg-blue-500 disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="min-h-5 text-sm text-red-400">{error}</p>
      </form>
    </div>
  );
}
