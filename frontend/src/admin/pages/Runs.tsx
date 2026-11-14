import { Fragment, useCallback, useEffect, useState } from "react";
import { api } from "../../shared/api";
import { Badge, Button, td, th, useLoad, when } from "../ui";
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
      <h1 className="mb-4 text-xl font-semibold">Runs</h1>
      <select value={status} onChange={(e) => setStatus(e.target.value)} className="mb-4 rounded bg-neutral-900 px-3 py-1 text-sm">
        {STATUSES.map((s) => <option key={s} value={s}>{s || "all statuses"}</option>)}
      </select>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
      <table className="w-full">
        <thead>
          <tr>{["Started", "Run", "User", "File", "Status", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data?.runs.map((r) => (
            <Fragment key={r.run_id}>
              <tr className={eventsOf === r.run_id ? "bg-inset" : ""}>
                <td className={td}>{when(r.created_at)}</td>
                <td className={`${td} font-mono text-xs`}>{r.run_id}</td>
                <td className={td}>{r.user ?? "—"}</td>
                <td className={td}>{r.file}</td>
                <td className={td}><Badge text={r.status} /><span className="ml-2 text-xs text-neutral-500">{where(r)}</span></td>
                <td className={td}>
                  <span className="flex gap-1">
                    <Button onClick={() => toggle(r.run_id)}>{open === r.run_id ? "Hide steps" : "Steps"}</Button>
                    <Button onClick={() => setEventsOf(eventsOf === r.run_id ? null : r.run_id)}>{eventsOf === r.run_id ? "Hide log" : "Log"}</Button>
                    {ACTIVE.includes(r.status) && <Button onClick={() => markFailed(r)}>Mark failed</Button>}
                    <Button kind="danger" onClick={() => remove(r)}>Delete data</Button>
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
                            <td className="py-1 pr-4"><Badge text={s.status} /></td>
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
      {logRun && (
        <RunEvents key={logRun.run_id} runId={logRun.run_id} file={logRun.file} user={logRun.user} status={logRun.status}
          live={ACTIVE.includes(logRun.status)} onClose={closeLog} />
      )}
    </div>
  );
}
