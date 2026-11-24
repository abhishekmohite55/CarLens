import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../../shared/api";
import { td, th, useLoad, when } from "../ui";
import { RunEvents } from "./RunEvents";

type Run = {
  run_id: string; file: string | null; status: string; failed_at: string | null; error: string | null; user: string | null;
  last_step: string | null; created_at: string;
};
type Step = { node: string; status: string; started_at: string; seconds: number | null; summary: string | null; error: string | null };
const ACTIVE = ["uploaded", "running", "awaiting_confirm"];
const STATUSES = ["", "running", "awaiting_confirm", "complete", "partial", "failed", "uploaded"];

// Where a run stopped (owner, 12 Nov): "failed at verify", "after locate".
function where(run: Run): string {
  if (run.status === "failed" && run.failed_at) return `at ${run.failed_at}`;
  if (run.status === "partial" && run.last_step) return `after ${run.last_step}`;
  return "";
}

const STATUS_CFG: Record<string, { color: string; label: string; icon: ReactNode }> = {
  complete: {
    color: "text-green-400",
    label: "complete",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" />
        <path d="M5 8l2 2 4-4" />
      </svg>
    ),
  },
  done: {
    color: "text-green-400",
    label: "done",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" />
        <path d="M5 8l2 2 4-4" />
      </svg>
    ),
  },
  failed: {
    color: "text-red-400",
    label: "failed",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
      </svg>
    ),
  },
  running: {
    color: "text-blue-400",
    label: "running",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="animate-spin" aria-hidden="true">
        <path d="M8 1.5A6.5 6.5 0 1 1 1.5 8" />
      </svg>
    ),
  },
  uploaded: {
    color: "text-sky-400",
    label: "uploaded",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 10.5V3.5M5 6.5l3-3 3 3" />
        <path d="M2.5 12.5h11" />
      </svg>
    ),
  },
  awaiting_confirm: {
    color: "text-purple-400",
    label: "waiting",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" />
        <path d="M8 5v3.25l2 1.25" />
      </svg>
    ),
  },
  partial: {
    color: "text-neutral-400",
    label: "stopped",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" />
        <rect x="5.5" y="5.5" width="5" height="5" rx="0.75" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  skipped: {
    color: "text-neutral-500",
    label: "skipped",
    icon: (
      <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" strokeDasharray="3 2" />
      </svg>
    ),
  },
};

const ALL_ICON = (
  <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
    <circle cx="8" cy="8" r="6.5" strokeDasharray="3 2" />
  </svg>
);

function StatusChip({ status }: { status: string }) {
  const cfg = STATUS_CFG[status];
  if (!cfg) return <span className="text-xs text-neutral-500">{status}</span>;
  return (
    <span className={cfg.color} title={cfg.label}>
      {cfg.icon}
    </span>
  );
}

function StatusSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const cfg = value ? (STATUS_CFG[value] ?? null) : null;
  return (
    <div className="relative">
      {open && <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />}
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative z-20 flex items-center gap-2 rounded-lg bg-neutral-900 px-3 py-1.5 text-sm text-neutral-200 ring-1 ring-neutral-800 transition-colors hover:bg-neutral-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span className={cfg ? cfg.color : "text-neutral-500"}>{cfg ? cfg.icon : ALL_ICON}</span>
        <span>{cfg ? cfg.label : "all statuses"}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
          className={`transition-transform duration-150 ${open ? "rotate-180" : ""}`}>
          <path d="M2 4l4 4 4-4" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1.5 w-48 overflow-hidden rounded-xl bg-neutral-900 shadow-xl ring-1 ring-neutral-800">
          {STATUSES.map((s) => {
            const c = s ? (STATUS_CFG[s] ?? null) : null;
            return (
              <button
                key={s || "all"}
                onClick={() => { onChange(s); setOpen(false); }}
                className={`flex w-full items-center gap-2.5 px-3 py-2 text-sm transition-colors hover:bg-neutral-800 ${value === s ? "bg-neutral-800/70" : ""}`}
              >
                <span className={c ? c.color : "text-neutral-500"}>{c ? c.icon : ALL_ICON}</span>
                <span className="text-neutral-200">{c ? c.label : "all statuses"}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ActionBtn({ onClick, label, children, danger = false, active = false }: {
  onClick: () => void; label: string; children: ReactNode; danger?: boolean; active?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className={`grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
        danger
          ? "text-red-400 hover:bg-red-900/40 hover:text-red-300"
          : active
            ? "bg-neutral-700 text-neutral-200"
            : "text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
      }`}
    >
      {children}
    </button>
  );
}

export function Runs() {
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const load = useCallback(() => api<{ runs: Run[] }>(`/api/admin/runs${status ? `?status=${status}` : ""}`), [status]);
  const { data, error, act, reload } = useLoad(load);
  const [eventsOf, setEventsOf] = useState<string | null>(null);
  const logRun = data?.runs.find((r) => r.run_id === eventsOf);
  const closeLog = useCallback(() => setEventsOf(null), []);

  // Live list (owner, 13 Nov): reload every 3 s while the page is visible; open steps follow too.
  useEffect(() => {
    const timer = setInterval(async () => {
      if (document.hidden) return;
      await reload();
      if (open) setSteps((await api<{ steps: Step[] }>(`/api/admin/runs/${open}`)).steps);
    }, 3000);
    return () => clearInterval(timer);
  }, [reload, open]);

  async function toggle(runId: string) {
    if (open === runId) return setOpen(null);
    setSteps((await api<{ steps: Step[] }>(`/api/admin/runs/${runId}`)).steps);
    setOpen(runId);
  }
  function markFailed(run: Run) {
    if (window.confirm(`Mark ${run.run_id} as failed? The user can start a new run; this one can still be resumed.`))
      act(() => api(`/api/admin/runs/${run.run_id}/fail`, { method: "POST" }));
  }
  function remove(run: Run) {
    if (window.confirm(`Delete all data of ${run.run_id} (video, frames, results, events)? Shared price data is kept. This cannot be undone.`))
      act(() => api(`/api/admin/runs/${run.run_id}`, { method: "DELETE" }));
  }

  return (
    <div className={logRun ? "xl:pr-[33rem]" : ""}>
      <div className="mb-6 flex items-center gap-3">
        <h1 className="font-display text-xl sm:text-3xl font-light tracking-tight text-ink">Runs</h1>
        <div className="ml-auto flex items-center gap-2">
          <StatusSelect value={status} onChange={setStatus} />
          <a href="/inspector" target="_blank" rel="noreferrer"
            className="flex items-center gap-1.5 rounded-lg bg-neutral-900 px-3 py-1.5 text-sm text-neutral-400 ring-1 ring-neutral-800 transition-colors hover:bg-neutral-800 hover:text-neutral-200">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="6.5" cy="6.5" r="4.5" />
              <path d="M10 10l3.5 3.5" />
            </svg>
            Inspector
          </a>
        </div>
      </div>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {/* Mobile cards */}
      <div className="sm:hidden space-y-2">
        {data?.runs.map((r) => (
          <div key={r.run_id} className="rounded-2xl bg-card px-4 py-3 shadow-card">
            <div className="flex items-center gap-2">
              <StatusChip status={r.status} />
              <span className="font-mono text-xs text-neutral-200">{r.run_id.slice(0, 8)}</span>
              <span className="ml-auto shrink-0 text-xs text-neutral-500">{when(r.created_at)}</span>
            </div>
            <div className="mt-0.5 text-xs text-neutral-500">
              {r.user ?? "—"}{r.file ? ` · ${r.file}` : ""}
              {where(r) && <span className="ml-1">{where(r)}</span>}
            </div>
            <div className="mt-2 flex items-center gap-0.5">
              <ActionBtn onClick={() => toggle(r.run_id)} label={open === r.run_id ? "Hide steps" : "Show steps"} active={open === r.run_id}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M2 5h12M2 8h12M2 11h7" />
                </svg>
              </ActionBtn>
              <ActionBtn onClick={() => setEventsOf(eventsOf === r.run_id ? null : r.run_id)} label={eventsOf === r.run_id ? "Hide log" : "Open log"} active={eventsOf === r.run_id}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="2" y="3" width="12" height="10" rx="1.5" />
                  <path d="M5 7h6M5 10h4" />
                </svg>
              </ActionBtn>
              {ACTIVE.includes(r.status) && (
                <ActionBtn onClick={() => markFailed(r)} label="Mark as failed">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M8 2.5L14 13H2L8 2.5z" />
                    <path d="M8 7v2.5" />
                    <circle cx="8" cy="11.5" r="0.75" fill="currentColor" stroke="none" />
                  </svg>
                </ActionBtn>
              )}
              <ActionBtn onClick={() => remove(r)} label="Delete run data" danger>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M3 4h10M6 4V2.5h4V4M5.5 4l.5 9h4l.5-9" />
                </svg>
              </ActionBtn>
            </div>
            {open === r.run_id && steps.length > 0 && (
              <div className="mt-2 space-y-1 border-t border-neutral-900 pt-2">
                {r.error && <p className="text-xs text-red-400">{r.error}</p>}
                {steps.map((s, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <StatusChip status={s.status} />
                    <span className="text-neutral-200">{s.node}</span>
                    <span className="text-neutral-500">{s.seconds !== null ? `${s.seconds}s` : "…"}</span>
                    {(s.error ?? s.summary) && <span className="min-w-0 truncate text-neutral-400">{s.error ?? s.summary}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {data && data.runs.length === 0 && <p className="mt-4 text-sm text-neutral-500">No runs.</p>}
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block">
        <table className="w-full">
          <thead>
            <tr>
              {["Started", "Run", "User", "File"].map((h) => <th key={h} className={th}>{h}</th>)}
              <th className={`${th} text-center`}>Status</th>
              <th className={th} />
            </tr>
          </thead>
          <tbody>
            {data?.runs.map((r) => (
              <Fragment key={r.run_id}>
                <tr className={eventsOf === r.run_id ? "bg-inset" : ""}>
                  <td className={td}>{when(r.created_at)}</td>
                  <td className={`${td} font-mono text-xs`}>{r.run_id}</td>
                  <td className={td}>{r.user ?? "—"}</td>
                  <td className={td}>{r.file}</td>
                  <td className="border-b border-neutral-900 px-3 py-2 text-sm align-middle">
                    <div className="flex flex-col items-center gap-0.5">
                      <StatusChip status={r.status} />
                      {where(r) && <span className="text-xs text-neutral-500">{where(r)}</span>}
                    </div>
                  </td>
                  <td className="border-b border-neutral-900 px-3 py-2 text-sm align-middle">
                    <span className="flex items-center gap-0.5">
                      <ActionBtn onClick={() => toggle(r.run_id)} label={open === r.run_id ? "Hide steps" : "Show steps"} active={open === r.run_id}>
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M2 5h12M2 8h12M2 11h7" />
                        </svg>
                      </ActionBtn>
                      <ActionBtn onClick={() => setEventsOf(eventsOf === r.run_id ? null : r.run_id)} label={eventsOf === r.run_id ? "Hide log" : "Open log"} active={eventsOf === r.run_id}>
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <rect x="2" y="3" width="12" height="10" rx="1.5" />
                          <path d="M5 7h6M5 10h4" />
                        </svg>
                      </ActionBtn>
                      {ACTIVE.includes(r.status) && (
                        <ActionBtn onClick={() => markFailed(r)} label="Mark as failed">
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M8 2.5L14 13H2L8 2.5z" />
                            <path d="M8 7v2.5" />
                            <circle cx="8" cy="11.5" r="0.75" fill="currentColor" stroke="none" />
                          </svg>
                        </ActionBtn>
                      )}
                      <ActionBtn onClick={() => remove(r)} label="Delete run data" danger>
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                          <path d="M3 4h10M6 4V2.5h4V4M5.5 4l.5 9h4l.5-9" />
                        </svg>
                      </ActionBtn>
                    </span>
                  </td>
                </tr>
                {open === r.run_id && (
                  <tr>
                    <td colSpan={6} className="bg-neutral-900 px-6 py-3">
                      {r.error && <p className="mb-2 text-sm text-red-400">{r.error}</p>}
                      <table className="w-full text-xs">
                        <tbody>
                          {steps.map((s, i) => (
                            <tr key={i}>
                              <td className="py-1 pr-4">{s.node}</td>
                              <td className="py-1 pr-4"><StatusChip status={s.status} /></td>
                              <td className="py-1 pr-4">{s.seconds !== null ? `${s.seconds} s` : "…"}</td>
                              <td className="py-1 text-neutral-400">{s.error ?? s.summary}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {data && data.runs.length === 0 && <p className="mt-4 text-sm text-neutral-500">No runs.</p>}
      </div>
      {logRun && (
        <RunEvents key={logRun.run_id} runId={logRun.run_id} file={logRun.file} user={logRun.user} status={logRun.status}
          live={ACTIVE.includes(logRun.status)} onClose={closeLog} />
      )}
    </div>
  );
}
