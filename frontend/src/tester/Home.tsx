// Stage F4: Home (docs/frontend/13-storyboard.md, Scenes 3–4; plan 12-frontend-plan.md S6–S7).
// The Lens is the upload pill; it becomes the file tile, the upload bar, the same-video card or a blocked state.
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api } from "../shared/api";
import { Lens } from "./Lens";
import { springs } from "./motion";
import { useSession } from "./session";
import { ThemeToggle } from "./theme";
import { ACTIVE, checkFile, durationText, sendVideo, sizeText, type Limits, type RunRow } from "./upload";

type Stage =
  | { kind: "ready" }
  | { kind: "picked"; file: File; url: string; duration?: number }
  | { kind: "uploading"; file: File; sent: number }
  | { kind: "same"; file: File; oldRunId: string; pendingId: string };

const onCanvas = "text-label rounded-full bg-canvas px-5 py-3 whitespace-nowrap text-ink disabled:opacity-60";
const quiet = "text-label rounded-full px-4 py-2 whitespace-nowrap opacity-75 hover:opacity-100";

const STATUS: Record<string, { word: string; tone: string }> = {
  uploaded: { word: "Not started", tone: "text-warn-text" },
  running: { word: "Running", tone: "text-ink" },
  awaiting_confirm: { word: "Waiting for you", tone: "text-ink font-medium" },
  complete: { word: "Done", tone: "text-ok-text" },
  partial: { word: "Stopped", tone: "text-ink-3" },
  failed: { word: "Stopped", tone: "text-danger-text" },
};

function statusWord(run: RunRow) {
  const s = STATUS[run.status] ?? { word: run.status, tone: "text-ink-3" };
  return run.status === "failed" && run.failed_at ? { ...s, word: `Stopped at ${run.failed_at}` } : s;
}

function dateText(iso: string) {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** One dot per run left; a spent dot curves up and away. */
function RunDots({ left }: { left: number }) {
  return (
    <div className="flex justify-center gap-1.5" aria-hidden>
      <AnimatePresence initial={false}>
        {Array.from({ length: Math.min(left, 20) }, (_, i) => (
          <motion.span key={i} layout transition={springs.rubber} exit={{ y: -40, x: 12, opacity: 0, scale: 0.6 }}
            className="h-2 w-2 rounded-full bg-ink" />
        ))}
      </AnimatePresence>
    </div>
  );
}

export function Home() {
  const { me, refresh, signOut } = useSession();
  const navigate = useNavigate();
  const [limits, setLimits] = useState<Limits | null>(null);
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [stage, setStage] = useState<Stage>({ kind: "ready" });
  const [problem, setProblem] = useState("");
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const loadRuns = useCallback(async () => setRuns((await api<{ runs: RunRow[] }>("/api/runs")).runs), []);
  useEffect(() => {
    api<{ upload: Limits }>("/api/config").then((c) => setLimits(c.upload)).catch(() => setProblem("Could not load the upload limits."));
    loadRuns().catch(() => setRuns([]));
  }, [loadRuns]);

  const isAdmin = me?.role === "admin";
  const runsLeft = me?.tokens ?? 0;
  const active = runs?.find((r) => ACTIVE.includes(r.status));
  const blocked = !isAdmin && stage.kind === "ready" && (active || runsLeft <= 0);

  const pick = (file: File | undefined) => {
    if (!file || !limits) return;
    const wrong = checkFile(file, limits);
    setProblem(wrong);
    if (!wrong) setStage({ kind: "picked", file, url: URL.createObjectURL(file) });
  };
  // The preview URL is released when the tile goes away.
  const previewUrl = stage.kind === "picked" ? stage.url : null;
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);

  const upload = async (file: File) => {
    setProblem("");
    setStage({ kind: "uploading", file, sent: 0 });
    const answer = await sendVideo(file, (sent) => setStage({ kind: "uploading", file, sent }));
    if (answer.kind === "run") {
      await refresh();
      navigate(`/run/${answer.runId}`);
    } else if (answer.kind === "same") {
      setStage({ kind: "same", file, oldRunId: answer.oldRunId, pendingId: answer.pendingId });
    } else {
      setProblem(answer.message);
      setStage({ kind: "ready" });
      await Promise.all([refresh(), loadRuns()]);
    }
  };

  const openOld = async (s: Extract<Stage, { kind: "same" }>) => {
    await api(`/api/uploads/${s.pendingId}`, { method: "DELETE" }).catch(() => {});
    navigate(`/run/${s.oldRunId}`);
  };
  const freshRun = async (s: Extract<Stage, { kind: "same" }>) => {
    try {
      const { run_id } = await api<{ run_id: string }>(`/api/uploads/${s.pendingId}/start`, { method: "POST" });
      await refresh();
      navigate(`/run/${run_id}`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not start the run.");
      setStage({ kind: "ready" });
      await Promise.all([refresh(), loadRuns()]);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (!blocked && stage.kind === "ready") pick(e.dataTransfer.files[0]);
  };

  let lens;
  if (blocked && active?.status === "uploaded") {
    // Start a fresh run (owner, 14 Nov): the old run ends partially, its token is not given back.
    const endIt = async () => {
      setProblem("");
      try {
        await api(`/api/runs/${active.run_id}/end`, { method: "POST" });
      } catch (e) {
        setProblem(e instanceof Error ? e.message : "Could not end that run.");
      }
      await Promise.all([refresh(), loadRuns()]);
    };
    lens = (
      <Lens scene="not-started" radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-3 p-6">
          <p className="text-heading">You have a video that hasn't started.</p>
          <p className="text-body opacity-80">{active.file}</p>
          <div className="flex flex-wrap gap-2">
            <Link to={`/run/${active.run_id}`} className={onCanvas}>Continue</Link>
            <button onClick={endIt} className={quiet}>Start a fresh run</button>
          </div>
          <p className="text-small opacity-70">Starting fresh ends this one. A new video uses 1 run.</p>
        </div>
      </Lens>
    );
  } else if (blocked && active) {
    lens = (
      <Lens scene="in-progress" radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-3 p-6">
          <p className="text-heading">{active.file} is {active.status === "awaiting_confirm" ? "waiting for you" : "running"}.</p>
          <p className="text-body opacity-80">Finish this run before starting another.</p>
          <Link to={`/run/${active.run_id}`} className={`${onCanvas} inline-block`}>Open run</Link>
        </div>
      </Lens>
    );
  } else if (blocked) {
    lens = (
      <Lens scene="no-runs" radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-2 p-6">
          <p className="text-heading">You have used all your runs.</p>
          <p className="text-body opacity-80">Ask the owner for more. Your earlier runs stay below.</p>
        </div>
      </Lens>
    );
  } else if (stage.kind === "picked") {
    const { file, url, duration } = stage;
    lens = (
      <Lens scene="picked" radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-4 p-5">
          {/* A still from the chosen file: the only place the user's own video appears (owner, 6 Nov). */}
          <video src={`${url}#t=0.5`} muted playsInline preload="metadata" className="aspect-video w-full rounded-input bg-canvas object-cover"
            onLoadedMetadata={(e) => {
              const d = e.currentTarget.duration;
              if (limits && d > limits.max_duration_sec) {
                setProblem(`This video is ${durationText(d)} long. The limit is ${durationText(limits.max_duration_sec)}.`);
                setStage({ kind: "ready" });
              } else setStage({ ...stage, duration: d });
            }} />
          <div>
            <p className="text-label break-all">{file.name}</p>
            <p className="text-small mt-1 tabular-nums opacity-75">
              {sizeText(file.size)}{duration ? `, ${durationText(duration)}` : ""}
            </p>
          </div>
          <p className="text-small opacity-80">{isAdmin ? "Admin account: no run limit." : `This uses 1 of your ${runsLeft} runs.`}</p>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => upload(file)} className={onCanvas}>Upload video</button>
            <button onClick={() => setStage({ kind: "ready" })} className={quiet}>Choose another</button>
          </div>
        </div>
      </Lens>
    );
  } else if (stage.kind === "uploading") {
    const pct = Math.min(100, Math.round((stage.sent / stage.file.size) * 100));
    lens = (
      <Lens scene="uploading" radius={7} tone="track" className="h-3.5 w-[min(80vw,22rem)]">
        <motion.div className="h-full rounded-full bg-ink" animate={{ width: `${pct}%` }} transition={springs.morph} />
      </Lens>
    );
  } else if (stage.kind === "same") {
    const old = runs?.find((r) => r.run_id === stage.oldRunId);
    lens = (
      <Lens scene="same" radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-4 p-6">
          <p className="text-heading">You uploaded this video {old ? `on ${dateText(old.created_at)}` : "before"}.</p>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => openOld(stage)} className={onCanvas}>Open the old run</button>
            <button onClick={() => freshRun(stage)} className={quiet}>
              {isAdmin ? "Start a fresh run" : `Start a fresh run (uses 1 of ${runsLeft})`}
            </button>
          </div>
          <p className="text-small opacity-75">We keep this upload for 30 minutes while you choose.</p>
        </div>
      </Lens>
    );
  } else {
    lens = (
      <Lens scene="ready" radius={dragging ? 40 : 32} spring="rubber" className={dragging ? "h-20" : "h-16"}>
        <div className="text-label flex h-full items-center gap-4 pr-2.5 pl-7">
          <span className="whitespace-nowrap">{dragging ? "Drop to upload" : "Drop a walkaround video"}</span>
          <button onClick={() => picker.current?.click()} disabled={!limits} className={onCanvas}>Choose video</button>
        </div>
      </Lens>
    );
  }

  return (
    <div className="min-h-svh bg-canvas text-ink"
      onDragOver={(e) => { e.preventDefault(); if (stage.kind === "ready" && !blocked) setDragging(true); }}
      onDragLeave={(e) => { if (!e.relatedTarget) setDragging(false); }} onDrop={onDrop}>
      <header className="flex items-center justify-between gap-3 px-4 pt-4 sm:px-8 sm:pt-6">
        <span className="text-heading">CarLens</span>
        <div className="flex items-center gap-1 sm:gap-2">
          <span className="text-small hidden text-ink-3 sm:inline">{me?.email}</span>
          <button onClick={async () => { await signOut(); navigate("/"); }} className="text-label rounded-full px-4 py-2 text-ink-2 hover:text-ink">
            Sign out
          </button>
          <ThemeToggle />
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-4 pb-24 sm:px-8">
        <section className="flex min-h-[22rem] flex-col items-center justify-center gap-5 pt-10">
          {lens}
          {stage.kind === "uploading" && (
            <p className="text-body tabular-nums text-ink-2">
              Uploading, {sizeText(stage.sent)} of {sizeText(stage.file.size)}
            </p>
          )}
          {problem && <p role="alert" className="text-body rounded-input bg-danger-soft px-4 py-3 text-center text-danger-text">{problem}</p>}
          {stage.kind === "ready" && !blocked && limits && (
            <p className="text-small text-center text-ink-3">
              {limits.allowed_types.join(", ")}, up to {limits.max_size_mb} MB and {durationText(limits.max_duration_sec)}.
            </p>
          )}
          {!isAdmin && (
            <div className="space-y-2 text-center">
              <RunDots left={runsLeft} />
              <p className="text-body text-ink-2">
                <span className="font-medium text-ink">{runsLeft} {runsLeft === 1 ? "run" : "runs"} left.</span> Each new video uses 1. Resuming a run is free.
              </p>
            </div>
          )}
          <input ref={picker} type="file" hidden accept={limits?.allowed_types.map((t) => `.${t}`).join(",")}
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        </section>

        <section className="mt-16">
          <h2 className="text-heading">My runs</h2>
          {runs && runs.length === 0 && <p className="text-body mt-4 text-ink-3">Your inspections will appear here.</p>}
          <ul className="mt-4 space-y-2">
            {runs?.map((run) => {
              const s = statusWord(run);
              return (
                <li key={run.run_id}>
                  <Link to={`/run/${run.run_id}`}
                    className="flex items-center justify-between gap-4 rounded-panel bg-surface px-5 py-4 shadow-panel transition-colors hover:bg-top">
                    <span className="min-w-0">
                      <span className="text-body block truncate">{run.file}</span>
                      <span className="text-small text-ink-3">{dateText(run.created_at)}</span>
                    </span>
                    <span className={`text-label shrink-0 ${s.tone}`}>{s.word}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      </main>
    </div>
  );
}
