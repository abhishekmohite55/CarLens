import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router";
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
  const { me, setMe, signOut } = useMe();

  if (me === undefined) return <div className="min-h-screen bg-page" />;
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
  const lead = "300ms cubic-bezier(.3, 1.35, .5, 1)";
  const trail = "480ms cubic-bezier(.3, 1.45, .45, 1) 70ms";
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

function Placeholder({ label, stage }: { label: string; stage: string }) {
  return (
    <div>
      <h1 className="mb-2 text-xl font-semibold">{label}</h1>
      <p className="text-neutral-500">Comes in stage {stage}.</p>
    </div>
  );
}
