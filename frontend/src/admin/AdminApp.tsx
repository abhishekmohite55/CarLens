import { NavLink, Navigate, Route, Routes } from "react-router";
import { SignIn } from "../shared/SignIn";
import { useMe } from "../shared/useMe";

// Admin sections (docs/platform/06-admin.md §1). Each fills in at its stage.
const SECTIONS = [
  { path: "dashboard", label: "Dashboard", stage: "6.4" },
  { path: "users", label: "Users & requests", stage: "6.2" },
  { path: "runs", label: "Runs", stage: "6.2" },
  { path: "config", label: "Config", stage: "6.3" },
  { path: "prompts", label: "Prompts", stage: "6.3" },
  { path: "tables", label: "Tables", stage: "6.4" },
  { path: "audit", label: "Audit log", stage: "6.2" },
];

export function AdminApp() {
  const { me, setMe, signOut } = useMe();

  if (me === undefined) return <div className="min-h-screen bg-neutral-950" />;
  if (me === null) return <SignIn title="CarLens admin" onSignedIn={setMe} />;
  if (me.role !== "admin") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 text-neutral-200">
        <p>This page is for the admin only.</p>
        <button onClick={signOut} className="rounded bg-neutral-800 px-4 py-2 hover:bg-neutral-700">Sign out</button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-neutral-950 text-neutral-200">
      <nav className="w-56 shrink-0 border-r border-neutral-800 p-4">
        <div className="mb-6 text-lg font-semibold">CarLens admin</div>
        <ul className="space-y-1">
          {SECTIONS.map((s) => (
            <li key={s.path}>
              <NavLink
                to={s.path}
                className={({ isActive }) => `block rounded px-3 py-2 text-sm ${isActive ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900"}`}
              >
                {s.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="flex-1">
        <header className="flex items-center justify-end gap-4 border-b border-neutral-800 px-6 py-3 text-sm text-neutral-400">
          <span>{me.email}</span>
          <button onClick={signOut} className="rounded bg-neutral-800 px-3 py-1 text-neutral-200 hover:bg-neutral-700">Sign out</button>
        </header>
        <main className="p-6">
          <Routes>
            <Route index element={<Navigate to="dashboard" replace />} />
            {SECTIONS.map((s) => (
              <Route key={s.path} path={s.path} element={<Placeholder label={s.label} stage={s.stage} />} />
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
