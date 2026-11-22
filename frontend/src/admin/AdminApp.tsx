import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router";
import { api } from "../shared/api";
import { SignIn } from "../shared/SignIn";
import { useMe } from "../shared/useMe";
import { Audit } from "./pages/Audit";
import { Config } from "./pages/Config";
import { Dashboard } from "./pages/Dashboard";
import { Prompts } from "./pages/Prompts";
import { Runs } from "./pages/Runs";
import { Tables } from "./pages/Tables";
import { Users } from "./pages/Users";
import { ThemeSwitch } from "./theme";

// Admin sections (docs/platform/06-admin.md §1). A section without a page shows "comes in stage …".
const SECTIONS: { path: string; label: string; stage: string; page?: () => React.JSX.Element }[] = [
  { path: "dashboard", label: "Dashboard", stage: "6.4", page: Dashboard },
  { path: "users", label: "Users & requests", stage: "6.2", page: Users },
  { path: "runs", label: "Runs", stage: "6.2", page: Runs },
  { path: "config", label: "Config", stage: "6.3", page: Config },
  { path: "prompts", label: "Prompts", stage: "6.3", page: Prompts },
  { path: "tables", label: "Tables", stage: "6.4", page: Tables },
  { path: "audit", label: "Audit log", stage: "6.2", page: Audit },
];

export function AdminApp() {
  const { me, setMe, signOut, refresh, problem } = useMe();

  if (me === undefined && problem) return <Unreachable problem={problem} onRetry={refresh} />;
  if (me === undefined) {
    return <div className="flex min-h-screen items-center justify-center bg-page font-admin text-sm text-ink-3">Connecting to CarLens…</div>;
  }
  if (me === null) return <SignIn title="CarLens admin" onSignedIn={setMe} />;
  if (me.role !== "admin") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-page text-ink">
        <p>This page is for the admin only.</p>
        <button onClick={signOut} className="rounded bg-neutral-800 px-4 py-2 hover:bg-neutral-700">Sign out</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-page font-admin text-ink">
      <header className="sticky top-0 z-30 bg-page/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-ink font-display text-sm font-semibold text-page" aria-hidden="true">CL</span>
            <span className="font-display text-lg font-medium tracking-tight">CarLens admin</span>
          </div>
          <div className="order-3 w-full xl:order-2 xl:flex xl:w-auto xl:flex-1 xl:justify-center">
            <NavCapsule />
          </div>
          <div className="order-2 ml-auto flex items-center gap-2 text-sm text-ink-2 xl:order-3 xl:ml-0">
            <span className="hidden max-w-[16rem] truncate md:inline">{me.email}</span>
            <ThemeSwitch />
            <button onClick={signOut} className="rounded-full bg-card px-4 py-1.5 text-ink shadow-card transition-colors hover:bg-inset focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">Sign out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-4 pb-10 pt-3 sm:px-6">
        <HealthBanner />
        <Routes>
          <Route index element={<Navigate to="dashboard" replace />} />
          {SECTIONS.map((s) => (
            <Route key={s.path} path={s.path} element={s.page ? <s.page /> : <Placeholder label={s.label} stage={s.stage} />} />
          ))}
          <Route path="*" element={<Navigate to="dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/** Section menu as a capsule. The highlight's leading edge moves first and the trailing edge follows with a small
 *  overshoot (rubber band, owner 12 Nov). On a phone the capsule scrolls sideways and keeps the open section in view. */
function NavCapsule() {
  const { pathname } = useLocation();
  const trackRef = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState<{ left: number; right: number; dir: 1 | -1; animate: boolean } | null>(null);

  const measure = useCallback((animate: boolean) => {
    const track = trackRef.current;
    const link = track?.querySelector<HTMLElement>('a[aria-current="page"]');
    if (!track || !link) return setEdge(null);
    const left = link.offsetLeft;
    const right = track.offsetWidth - (link.offsetLeft + link.offsetWidth);
    setEdge((old) => ({ left, right, dir: old && left < old.left ? -1 : 1, animate: animate && old !== null }));
    link.scrollIntoView({ block: "nearest", inline: "nearest", behavior: animate ? "smooth" : "auto" });
  }, []);

  useLayoutEffect(() => measure(true), [pathname, measure]);
  useEffect(() => {
    // Widths change when the typefaces arrive or the window resizes: follow without the stretch.
    const track = trackRef.current;
    if (!track) return;
    const observer = new ResizeObserver(() => measure(false));
    observer.observe(track);
    return () => observer.disconnect();
  }, [measure]);

  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const lead = "250ms cubic-bezier(.4, 0, .2, 1)";
  const trail = "380ms cubic-bezier(.4, 0, .6, 1) 60ms";
  const transition = !edge?.animate || reduce ? "none"
    : edge.dir === 1 ? `right ${lead}, left ${trail}` : `left ${lead}, right ${trail}`;

  return (
    <nav aria-label="Sections" className="no-scrollbar -mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <div className="inline-flex rounded-full bg-card p-1 shadow-card">
        <div ref={trackRef} className="relative flex">
          {edge && (
            <span aria-hidden="true" className="absolute inset-y-0 rounded-full bg-ink"
              style={{ left: edge.left, right: edge.right, transition }} />
          )}
          {SECTIONS.map((s) => (
            <NavLink key={s.path} to={s.path}
              className={({ isActive }) => `relative whitespace-nowrap rounded-full px-4 py-2 text-sm transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${isActive ? "text-page" : "text-ink-2 hover:text-ink"}`}>
              {s.label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}

/** Step 9.3: signing in needs the database. When the backend cannot answer, say why (public /api/health) instead of a
 * blank page; retries every 15 s. */
function Unreachable({ problem, onRetry }: { problem: string; onRetry: () => void }) {
  const [health, setHealth] = useState<{ status: string; version: string } | null>(null);
  useEffect(() => {
    const ask = () => api<{ status: string; version: string }>("/api/health").then(setHealth).catch(() => setHealth(null));
    void ask();
    const timer = setInterval(() => { void ask(); onRetry(); }, 15_000);
    return () => clearInterval(timer);
  }, [onRetry]);
  return (
    <div className="flex min-h-screen items-center justify-center bg-page p-6 font-admin text-ink">
      <section role="alert" className="max-w-lg rounded-2xl bg-card p-6 shadow-card">
        <h1 className="font-display text-2xl">CarLens admin can't sign you in right now</h1>
        <p className="mt-3 text-sm text-ink-2">
          {health === null ? "The backend does not answer: it may be restarting or stopped."
            : health.status === "degraded" ? "The backend is running but degraded: most likely its database is not reachable. Signing in needs the database."
            : "The backend answered with an error."}
        </p>
        <p className="mt-2 text-xs text-ink-3">Details: {problem}{health ? ` · health ${health.status}, version ${health.version}` : ""}</p>
        <button onClick={onRetry} className="mt-4 rounded-full bg-ink px-4 py-1.5 text-sm text-page focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">Try again</button>
        <p className="mt-2 text-xs text-ink-3">Tries again by itself every 15 seconds.</p>
      </section>
    </div>
  );
}

type Health = { status: "ok" | "degraded"; version: string; problems: { level: "error" | "warning"; message: string }[] };

/** Step 9.3: what the admin must know (database newer than the code, failed migration, maintenance left on, S3).
 * Asked on load and every minute; shown on every admin page. Says nothing when all is well. */
function HealthBanner() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  useEffect(() => {
    let alive = true;
    const ask = () => api<Health>("/api/admin/health")
      .then((h) => { if (alive) { setHealth(h); setUnreachable(false); setCheckedAt(new Date()); } })
      .catch(() => { if (alive) setUnreachable(true); });
    void ask();
    const timer = setInterval(() => void ask(), 60_000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const problems = unreachable
    ? [{ level: "error" as const, message: "The backend did not answer the health check. It may be restarting." }]
    : health?.problems ?? [];
  if (problems.length === 0) {
    if (!health || !checkedAt) return null; // first answer not in yet: never flash green
    // Owner, 20 Nov 2026: a calm green strip when all is well, so a healthy app is visible too.
    return (
      <output
        className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl bg-green-900 px-4 py-2 text-sm text-green-200 shadow-card">
        <span className="relative flex h-2.5 w-2.5" aria-hidden="true">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-40 motion-reduce:animate-none" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-400" />
        </span>
        <span className="font-medium">All systems healthy</span>
        <span className="opacity-75">version {health.version}</span>
        <span className="opacity-75">checked {checkedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
      </output>
    );
  }
  const isError = problems.some((p) => p.level === "error");
  return (
    <div role={isError ? "alert" : "status"}
      className={`mb-4 rounded-2xl px-4 py-3 text-sm shadow-card ${isError ? "bg-bad text-page" : "bg-card text-ink"}`}>
      <p className="font-medium">{isError ? "CarLens is degraded: new runs are refused" : "Needs your attention"}
        {health?.version ? <span className="ml-2 font-normal opacity-75">version {health.version}</span> : null}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {problems.map((p, i) => <li key={i}>{p.message}</li>)}
      </ul>
    </div>
  );
}

function Placeholder({ label, stage }: { label: string; stage: string }) {
  return (
    <div>
      <h1 className="mb-2 text-xl font-semibold">{label}</h1>
      <p className="text-neutral-500">Comes in stage {stage}.</p>
    </div>
  );
}
