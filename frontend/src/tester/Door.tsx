// Stage F3: the door (docs/frontend/13-storyboard.md, Scene 2; copy from 10-site-content.md §5, platform/05-login.md).
// Sign in, request access, waiting for approval, refused. The Lens is the card; switching screens morphs it.
import { motion } from "motion/react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { api, ApiError, type Me } from "../shared/api";
import { loadGoogle, setGoogleHandler } from "./google";
import { Lens } from "./Lens";
import { springs } from "./motion";
import { homeFor, useSession } from "./session";

const field = "text-body w-full rounded-input bg-canvas px-4 py-3 text-ink outline-none placeholder:text-ink-3 focus:ring-2 focus:ring-line-strong";
const primary = "text-label w-full rounded-full bg-canvas px-5 py-3.5 text-ink disabled:opacity-60";
const quiet = "text-label rounded-full px-4 py-2 opacity-75 hover:opacity-100";

/** The page around the card: wordmark on top, card centred. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col bg-canvas text-ink">
      <header className="px-4 pt-4 sm:px-8 sm:pt-6">
        <Link to="/" className="text-heading">CarLens</Link>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">{children}</main>
    </div>
  );
}

/** Fields arrive one after another: each starts as a hairline and opens into its full height. */
function Arrive({ order, children }: { order: number; children: ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, scaleY: 0.08 }} animate={{ opacity: 1, scaleY: 1 }}
      transition={{ ...springs.morph, delay: 0.12 + order * 0.07 }} style={{ originY: 0 }}>
      {children}
    </motion.div>
  );
}

function Problem({ text }: { text: string }) {
  if (!text) return null;
  return <p role="alert" className="text-body rounded-input bg-danger-soft px-4 py-3 text-danger-text">{text}</p>;
}

function GoogleButton({ onError }: { onError: (text: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const { setMe } = useSession();
  const navigate = useNavigate();
  const [state, setState] = useState<"loading" | "ready" | "off">("loading");

  useEffect(() => {
    let live = true;
    setGoogleHandler(async (credential) => {
      try {
        const me = await api<Me>("/api/auth/google", { method: "POST", body: { credential } });
        setMe(me);
        navigate(homeFor(me.status));
      } catch (e) {
        onError(e instanceof Error ? e.message : "Google sign-in failed. Try again.");
      }
    });
    loadGoogle().then((google) => {
      if (!live) return;
      if (!google || !box.current) return setState("off");
      google.renderButton(box.current, {
        theme: "outline", size: "large", shape: "pill", text: "continue_with",
        width: Math.min(400, Math.round(box.current.clientWidth)),
      });
      setState("ready");
    });
    return () => { live = false; };
  }, [navigate, onError, setMe]);

  if (state === "off") return null;
  return (
    <>
      <div className="text-small flex items-center gap-3 opacity-60" aria-hidden>
        <span className="h-px flex-1 bg-current opacity-40" />or<span className="h-px flex-1 bg-current opacity-40" />
      </div>
      <div ref={box} className="flex min-h-11 justify-center" />
    </>
  );
}

/** Sign in and Request access: the same card; the title swaps and the height adjusts. */
export function DoorForm({ mode }: { mode: "sign-in" | "request" }) {
  const signIn = mode === "sign-in";
  const { setMe } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);

  useEffect(() => setProblem(""), [mode]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setProblem("");
    setBusy(true);
    try {
      const me = await api<Me>(signIn ? "/api/auth/login" : "/api/auth/signup", { method: "POST", body: { email, password } });
      setMe(me);
      navigate(homeFor(me.status));
    } catch (e) {
      if (e instanceof ApiError && e.code === "code_required") setProblem("This is the admin account. Sign in on the admin app.");
      else setProblem(e instanceof Error ? e.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame>
      <Lens scene={mode} radius={32} className="w-[min(92vw,26rem)]">
        <form onSubmit={submit} className="space-y-4 p-6 sm:p-8">
          <h1 className="text-title">{signIn ? "Sign in to CarLens" : "Request access"}</h1>
          {!signIn && <p className="text-body opacity-80">The owner approves each request. You can use CarLens once you are approved.</p>}
          <Arrive order={0}>
            <label className="text-label block space-y-2">
              <span className="opacity-80">Email</span>
              <input className={field} type="email" autoComplete="username" required value={email}
                onChange={(e) => setEmail(e.target.value)} />
            </label>
          </Arrive>
          <Arrive order={1}>
            <label className="text-label block space-y-2">
              <span className="opacity-80">Password</span>
              <input className={field} type="password" autoComplete={signIn ? "current-password" : "new-password"} required
                value={password} onChange={(e) => setPassword(e.target.value)} />
              {!signIn && <span className="text-small block opacity-70">At least 10 characters.</span>}
            </label>
          </Arrive>
          <Problem text={problem} />
          <Arrive order={2}>
            <button disabled={busy} className={primary}>
              {busy ? (signIn ? "Signing in" : "Sending request") : signIn ? "Sign in" : "Request access"}
            </button>
          </Arrive>
          <Arrive order={3}><GoogleButton onError={setProblem} /></Arrive>
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            {signIn ? (
              <>
                <Link to="/request-access" className={quiet}>Request access</Link>
                <button type="button" onClick={() => setForgot(true)} className={quiet}>Forgot password?</button>
              </>
            ) : (
              <Link to="/sign-in" className={quiet}>I already have an account</Link>
            )}
          </div>
          {forgot && signIn && <p className="text-small opacity-80">Ask the owner to reset it.</p>}
        </form>
      </Lens>
    </Frame>
  );
}

/** A dot that travels round the card's edge, lap after lap: the only movement while waiting. */
function EdgeDot({ tone }: { tone: "travel" | "ok" | "stop" }) {
  const colour = tone === "ok" ? "var(--c-ok)" : tone === "stop" ? "var(--c-danger)" : "currentColor";
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
      <motion.rect x="3" y="3" rx="26" pathLength={100} fill="none" stroke={colour} strokeWidth="5" strokeLinecap="round"
        strokeDasharray="0.01 99.99" style={{ width: "calc(100% - 6px)", height: "calc(100% - 6px)" }}
        animate={tone === "travel" ? { strokeDashoffset: [0, -100] } : undefined}
        transition={{ duration: 7, ease: "linear", repeat: Infinity }} />
    </svg>
  );
}

/** Pending or refused: the card shrinks to a small one and waits. */
export function Waiting() {
  const { me, refresh, signOut } = useSession();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(false);
  const rejected = me?.status === "rejected";

  const check = async () => {
    setChecking(true);
    try {
      await refresh();
    } finally {
      setChecking(false);
    }
  };
  // Checked again whenever the person comes back to this tab.
  useEffect(() => {
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const leave = async () => {
    await signOut();
    navigate("/");
  };

  return (
    <Frame>
      <Lens scene={rejected ? "refused" : "waiting"} radius={32} className="w-[min(92vw,24rem)]">
        <EdgeDot tone={rejected ? "stop" : "travel"} />
        <div className="space-y-4 p-6 sm:p-8">
          {rejected ? (
            <>
              <h1 className="text-heading">Your request was not approved.</h1>
              <p className="text-body opacity-90">Ask the owner if this is a mistake.</p>
            </>
          ) : (
            <>
              <h1 className="text-heading">Request sent.</h1>
              <p className="text-body opacity-80">You can use CarLens once the owner approves you.</p>
              <p className="text-small break-all opacity-70">{me?.email}</p>
            </>
          )}
          <div className="flex flex-wrap gap-2 pt-2">
            {!rejected && (
              <button onClick={check} disabled={checking} className="text-label rounded-full bg-canvas px-5 py-3 text-ink disabled:opacity-60">
                {checking ? "Checking" : "Check again"}
              </button>
            )}
            <button onClick={leave} className={quiet}>Sign out</button>
          </div>
        </div>
      </Lens>
    </Frame>
  );
}

/** Home arrives in stage F4; until then an approved person lands here. */
export function HomeSoon() {
  const { me, signOut } = useSession();
  const navigate = useNavigate();
  return (
    <Frame>
      <Lens scene="home" radius={32} className="w-[min(92vw,24rem)]">
        <div className="space-y-3 p-6 sm:p-8">
          <h1 className="text-heading">You are in.</h1>
          <p className="text-body opacity-80">Signed in as {me?.email}. {me?.role === "admin" ? "Admin account." : `${me?.tokens} runs left.`}</p>
          <p className="text-small opacity-70">Uploading arrives in the next stage.</p>
          <button onClick={async () => { await signOut(); navigate("/"); }} className={quiet}>Sign out</button>
        </div>
      </Lens>
    </Frame>
  );
}

export function NotFound() {
  return (
    <Frame>
      <Lens scene="not-found" radius={32} className="w-[min(92vw,24rem)]">
        <div className="space-y-4 p-6 sm:p-8">
          <h1 className="text-heading">This page does not exist.</h1>
          <Link to="/" className="text-label inline-block rounded-full bg-canvas px-5 py-3 text-ink">Go to the start</Link>
        </div>
      </Lens>
    </Frame>
  );
}
