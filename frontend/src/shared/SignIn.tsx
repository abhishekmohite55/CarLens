import { useState, type FormEvent } from "react";
import { api, ApiError, type Me } from "./api";

/** Two-step sign-in: email+password, then (if admin) authenticator code.
 *  When the backend returns code_required the form advances to step 2 without
 *  showing an error — the user's credentials were accepted. */
export function SignIn({ title, onSignedIn }: { title: string; onSignedIn: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<1 | 2>(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      onSignedIn(await api<Me>("/api/auth/login", { method: "POST", body: { email, password, code: code || null } }));
    } catch (e) {
      if (e instanceof ApiError && e.code === "code_required") {
        setStep(2);
        // credentials accepted — not an error
      } else {
        setError(e instanceof Error ? e.message : "Sign-in failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  const fieldBase =
    "mt-1.5 w-full rounded-lg border border-neutral-700 bg-neutral-800/60 px-3 py-2.5 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus-visible:border-blue-500 focus-visible:ring-2 focus-visible:ring-blue-500/20";

  return (
    <div className="flex min-h-screen bg-neutral-950 font-admin">
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-14">
        <div className="mb-8 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-[11px] bg-neutral-100 font-display text-sm font-semibold text-neutral-950">
            CL
          </span>
          <span className="font-display text-base font-medium text-neutral-100">CarLens admin</span>
        </div>

        <div className="w-full max-w-sm">
          {/* step indicator */}
          <div className="mb-6 flex items-center gap-2 text-xs text-neutral-500">
            <StepDot n={1} active={step === 1} done={step > 1} label="Credentials" />
            <span className="h-px flex-1 bg-neutral-800" />
            <StepDot n={2} active={step === 2} done={false} label="Authenticator" />
          </div>

          <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-7 shadow-[0_16px_48px_-16px_#000000cc]">
            <h1 className="mb-1 font-display text-xl font-semibold text-neutral-100">
              {step === 1 ? "Sign in" : "Two-step verification"}
            </h1>
            <p className="mb-6 text-sm text-neutral-400">
              {step === 1
                ? title
                : "Enter the 6-digit code from your authenticator app."}
            </p>

            {/* credentials-accepted tick for step 2 */}
            {step === 2 && (
              <div className="mb-5 flex items-center gap-2">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-green-950/60 text-green-400">
                  <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.75">
                    <path d="M2 6l2.5 2.5 5.5-5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className="text-sm text-neutral-400">{email}</span>
              </div>
            )}

            <form onSubmit={submit} className="space-y-4">
              {step === 1 ? (
                <>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-neutral-400">Email</span>
                    <input
                      className={fieldBase}
                      type="email"
                      autoComplete="username"
                      required
                      placeholder="admin@example.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-medium text-neutral-400">Password</span>
                    <input
                      className={`${fieldBase} font-mono tracking-wide`}
                      type="password"
                      autoComplete="current-password"
                      required
                      placeholder="••••••••"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </label>
                </>
              ) : (
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-neutral-400">Authenticator code</span>
                  <input
                    className={`${fieldBase} text-center font-mono text-xl tracking-[0.35em]`}
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    placeholder="000000"
                    autoFocus
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  />
                  <p className="mt-2 text-xs text-neutral-600">Open your authenticator app to find the code.</p>
                </label>
              )}

              {error && (
                <p role="alert" className="rounded-lg border border-red-900 bg-red-950/40 px-3 py-2.5 text-sm text-red-400">
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={busy || (step === 2 && code.length < 6)}
                className="mt-1 w-full rounded-lg bg-neutral-100 py-2.5 text-sm font-medium text-neutral-950 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? (step === 1 ? "Checking credentials…" : "Verifying code…") : step === 1 ? "Continue" : "Sign in"}
              </button>

              {step === 2 && (
                <button
                  type="button"
                  className="w-full text-center text-xs text-neutral-600 hover:text-neutral-400"
                  onClick={() => { setStep(1); setCode(""); setError(""); }}
                >
                  Use a different account
                </button>
              )}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

function StepDot({ n, active, done, label }: { n: number; active: boolean; done: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold
          ${active ? "bg-blue-600 text-white" : done ? "bg-green-700 text-green-200" : "bg-neutral-800 text-neutral-600"}`}
      >
        {done ? (
          <svg className="h-3 w-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2.5 6l2.5 2.5 4.5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : n}
      </span>
      <span className={active ? "text-neutral-300" : "text-neutral-600"}>{label}</span>
    </span>
  );
}
