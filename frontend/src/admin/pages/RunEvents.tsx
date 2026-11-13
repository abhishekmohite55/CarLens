// Run log (owner, 13 Nov): every event of one run, live while the run works, the saved log once it has ended.
// Reads the run's events.jsonl through the files route (admin may read any run). It does not open the run's live
// stream (/api/runs/{id}/events), because opening that stream starts a run that has not started yet.
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Badge } from "../ui";

type RunEvent = { seq: number; ts: string; node: string; type: string; data?: Record<string, unknown> };

const POLL_MS = 1500;
const TYPE_LABEL: Record<string, string> = {
  node_started: "started", node_progress: "progress", node_done: "done", node_failed: "failed",
  node_skipped: "skipped", packet: "packet", awaiting_confirm: "waiting for confirm", run_done: "run ended",
};
const DOT: Record<string, string> = {
  node_started: "bg-accent", node_done: "bg-green-400", node_failed: "bg-red-400", node_skipped: "bg-ink-3",
  awaiting_confirm: "bg-purple-400", run_done: "bg-ink", packet: "border-2 border-accent bg-card", node_progress: "bg-line",
};

function detail(e: RunEvent): string {
  const d = e.data ?? {};
  if (e.type === "packet") return `${d.from} to ${d.to}: ${d.label}`;
  if (e.type === "run_done") {
    if (d.status === "failed") return `failed at ${d.failed_at ?? "?"}${d.error ? `: ${d.error}` : ""}`;
    if (d.stopped_after) return `stopped after ${d.stopped_after}`;
    return String(d.status ?? "");
  }
  const text = d.error ?? d.message ?? d.summary ?? d.reason ?? d.label ?? "";
  return typeof text === "string" ? text : JSON.stringify(text);
}

const clock = (ts: string) => new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

function gap(ms: number): string {
  if (ms < 1000) return "";
  const s = ms / 1000;
  return s < 60 ? `+${s.toFixed(1)}s` : `+${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

/** If the panel breaks, it shows the error instead of blanking the whole admin page. */
class Guard extends Component<{ children: ReactNode }, { error: string }> {
  state = { error: "" };
  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
  render() {
    return this.state.error ? <p className="p-5 text-sm text-bad">The run log could not be shown: {this.state.error}</p> : this.props.children;
  }
}

type Props = { runId: string; file: string | null; user: string | null; status: string; live: boolean; onClose: () => void };

/** A floating panel on top of the page (attached to <body>): right side on a computer, bottom sheet on a phone. */
export function RunEvents(props: Props) {
  return createPortal(
    <aside aria-label={`Run log of ${props.runId}`}
      className="fixed inset-x-2 bottom-2 z-50 flex max-h-[78vh] flex-col overflow-hidden rounded-[24px] bg-card font-admin text-ink shadow-card ring-1 ring-line
        md:inset-x-auto md:top-24 md:right-4 md:bottom-4 md:max-h-none md:w-[32rem]">
      <Guard><Panel {...props} /></Guard>
    </aside>,
    document.body,
  );
}

function Panel({ runId, file, user, status, live, onClose }: Props) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [node, setNode] = useState("");
  const [showProgress, setShowProgress] = useState(true);
  const [search, setSearch] = useState("");
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const [follow, setFollow] = useState(true);
  const list = useRef<HTMLDivElement>(null);
  const ended = events.some((e) => e.type === "run_done");

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch(`/api/runs/${runId}/files/events.jsonl`, { cache: "no-store", signal });
      if (response.status === 404) {
        setError("No events recorded for this run yet.");
      } else if (!response.ok) {
        setError(`Could not read the log (${response.status}).`);
      } else {
        const rows: RunEvent[] = [];
        for (const line of (await response.text()).split("\n")) {
          if (!line.trim()) continue;
          try {
            rows.push(JSON.parse(line) as RunEvent);
          } catch {
            // A line still being written: picked up on the next read.
          }
        }
        setEvents((old) => (old.length === rows.length ? old : rows));
        setError("");
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) setError("Could not read the log.");
    } finally {
      setLoaded(true);
    }
  }, [runId]);

  // First read; then every 1.5 s while the run is active (stops by itself when the run ends).
  useEffect(() => {
    const abort = new AbortController();
    void load(abort.signal);
    let timer: number | undefined;
    if (live) {
      timer = window.setInterval(() => {
        if (!document.hidden) void load(abort.signal);
      }, POLL_MS);
    }
    return () => {
      abort.abort();
      window.clearInterval(timer);
    };
  }, [load, live]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const nodes = useMemo(() => [...new Set(events.map((e) => e.node))], [events]);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return events.filter((e) => (!node || e.node === node)
      && (showProgress || e.type !== "node_progress")
      && (!q || `${e.node} ${e.type} ${detail(e)}`.toLowerCase().includes(q)));
  }, [events, node, showProgress, search]);

  // Keep the newest event in view while following; scrolling up stops following.
  useEffect(() => {
    const box = list.current;
    if (box && follow) box.scrollTop = box.scrollHeight;
  }, [shown.length, follow]);

  function onScroll() {
    const box = list.current;
    if (box) setFollow(box.scrollHeight - box.scrollTop - box.clientHeight < 40);
  }

  function download() {
    const blob = new Blob([events.map((e) => JSON.stringify(e)).join("\n") + "\n"], { type: "application/x-ndjson" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${runId}-events.jsonl`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  const first = events[0]?.ts;
  const last = events[events.length - 1]?.ts;
  const total = first && last ? gap(new Date(last).getTime() - new Date(first).getTime()).replace("+", "") : "";
  const isLive = live && !ended;

  return (
    <>
      <header className="flex items-start justify-between gap-3 px-5 pb-3 pt-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="font-display text-lg font-medium tracking-tight">Run log</h2>
            {isLive ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-inset px-2.5 py-0.5 text-xs text-ink-2">
                <span className="h-2 w-2 rounded-full bg-green-400 motion-safe:animate-pulse" />Live
              </span>
            ) : (
              <span className="rounded-full bg-inset px-2.5 py-0.5 text-xs text-ink-2">Saved log</span>
            )}
          </div>
          <p className="mt-1 truncate text-xs text-ink-3" title={runId}>
            <span className="font-mono">{runId}</span>{file ? `, ${file}` : ""}{user ? `, ${user}` : ""}
          </p>
          <p className="mt-1.5 flex items-center gap-2 text-xs text-ink-3">
            <Badge text={status} />
            <span className="tabular-nums">{events.length} events{total ? `, ${total}` : ""}</span>
          </p>
        </div>
        <button onClick={onClose} aria-label="Close the run log" title="Close (Esc)"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-inset text-ink-2 transition-colors hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </header>

      <div className="space-y-2 border-b border-line px-5 pb-3">
        <div className="no-scrollbar -mx-5 flex gap-1 overflow-x-auto px-5">
          {["", ...nodes].map((n) => (
            <button key={n || "all"} onClick={() => setNode(n)}
              className={`whitespace-nowrap rounded-full px-3 py-1 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${node === n ? "bg-ink text-page" : "bg-inset text-ink-2 hover:text-ink"}`}>
              {n || "All steps"}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search the log"
            className="min-w-0 flex-1 rounded-full bg-inset px-3.5 py-1.5 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent" />
          <label className="flex shrink-0 cursor-pointer items-center gap-1.5 text-xs text-ink-2">
            <input type="checkbox" checked={showProgress} onChange={(e) => setShowProgress(e.target.checked)} className="accent-[var(--t-accent)]" />
            Progress
          </label>
        </div>
      </div>

      <div ref={list} onScroll={onScroll} className="relative flex-1 overflow-y-auto px-5 py-3">
        {!loaded && <p className="py-6 text-center text-sm text-ink-3">Reading the log…</p>}
        {loaded && error && <p className="rounded-2xl bg-inset px-4 py-6 text-center text-sm text-ink-3">{error}</p>}
        {loaded && !error && shown.length === 0 && (
          <p className="rounded-2xl bg-inset px-4 py-6 text-center text-sm text-ink-3">{events.length ? "No events match the filter." : "No events yet."}</p>
        )}
        <ol className="relative">
          {shown.map((e, i) => {
            const prev = shown[i - 1];
            const after = prev ? gap(new Date(e.ts).getTime() - new Date(prev.ts).getTime()) : "";
            const failed = e.type === "node_failed" || (e.type === "run_done" && e.data?.status === "failed");
            const isOpen = openSeq === e.seq;
            return (
              <li key={e.seq} className="relative pl-6">
                {i < shown.length - 1 && <span aria-hidden="true" className="absolute left-[5px] top-4 h-full w-px bg-line" />}
                <span aria-hidden="true" className={`absolute left-0 top-[7px] h-[11px] w-[11px] rounded-full ${DOT[e.type] ?? "bg-ink-3"}`} />
                <button onClick={() => setOpenSeq(isOpen ? null : e.seq)} aria-expanded={isOpen}
                  className={`mb-1 w-full rounded-2xl px-3 py-1.5 text-left transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${failed ? "bg-red-900/35" : "hover:bg-inset"} ${isOpen ? "bg-inset" : ""}`}>
                  <span className="flex flex-wrap items-baseline gap-x-2 text-xs">
                    <span className="tabular-nums text-ink-3">{clock(e.ts)}</span>
                    <span className="font-medium text-ink">{e.node}</span>
                    <span className={failed ? "text-bad" : "text-ink-2"}>{TYPE_LABEL[e.type] ?? e.type}</span>
                    {after && <span className="ml-auto tabular-nums text-ink-3">{after}</span>}
                  </span>
                  {detail(e) && (
                    <span className={`mt-0.5 block break-words text-[13px] leading-snug ${failed ? "text-bad" : "text-ink-2"} ${e.type === "node_progress" ? "text-ink-3" : ""}`}>
                      {detail(e)}
                    </span>
                  )}
                </button>
                {isOpen && (
                  <pre className="mb-2 ml-3 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-2xl bg-inset p-3 font-mono text-[11px] leading-relaxed text-ink-2">
                    {JSON.stringify(e, null, 2)}
                  </pre>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <footer className="flex items-center justify-between gap-2 border-t border-line px-5 py-3">
        {!follow ? (
          <button onClick={() => setFollow(true)}
            className="rounded-full bg-ink px-3.5 py-1.5 text-xs text-page focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            Jump to latest
          </button>
        ) : <span className="text-xs text-ink-3">{isLive ? "Following new events" : "Click an event for its raw JSON"}</span>}
        <button onClick={download} disabled={!events.length}
          className="rounded-full bg-inset px-3.5 py-1.5 text-xs text-ink-2 transition-colors hover:text-ink disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Download .jsonl
        </button>
      </footer>
    </>
  );
}
