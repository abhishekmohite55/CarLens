import { NavLink, Navigate, Route, Routes } from "react-router";
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
    <div className="flex min-h-screen bg-page font-admin text-ink">
      <nav className="sticky top-0 flex h-screen w-60 shrink-0 flex-col p-4">
        <div className="mb-8 flex items-center gap-2.5 px-2 pt-1">
          <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-ink font-display text-sm font-semibold text-page" aria-hidden="true">CL</span>
          <span className="font-display text-lg font-medium tracking-tight">CarLens admin</span>
        </div>
        <ul className="space-y-1">
          {SECTIONS.map((s) => (
            <li key={s.path}>
              <NavLink
                to={s.path}
                className={({ isActive }) => `block rounded-full px-4 py-2 text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${isActive ? "bg-ink text-page" : "text-ink-2 hover:bg-card hover:text-ink"}`}
              >
                {s.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-end gap-3 px-6 pb-2 pt-5 text-sm text-ink-2">
          <span className="truncate">{me.email}</span>
          <ThemeSwitch />
          <button onClick={signOut} className="rounded-full bg-card px-4 py-1.5 text-ink shadow-card transition-colors hover:bg-inset focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">Sign out</button>
        </header>
        <main className="p-6 pt-2">
          <Routes>
            <Route index element={<Navigate to="dashboard" replace />} />
            {SECTIONS.map((s) => (
              <Route key={s.path} path={s.path} element={s.page ? <s.page /> : <Placeholder label={s.label} stage={s.stage} />} />
            ))}
            <Route path="*" element={<Navigate to="dashboard" replace />} />
          </Routes>
        </main>
      </div>
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
