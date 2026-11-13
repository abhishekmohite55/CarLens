// Stage F5: the run page, part 1 (docs/frontend/13-storyboard.md, Scenes 5–8): find moments, frames, plate, verify.
// Everything on screen is driven by the run's real events; animations loop only while a step really runs (rule 2).
// Testers see no Sent / Received (owner, 14 Nov).
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router";
import { Car3D } from "./Car3D";
import { ConfirmCard, type ConfirmPayload } from "./ConfirmCard";
import { SPOTS, VIEWS, type Spot } from "./car";
import { Lens } from "./Lens";
import { springs, swap } from "./motion";
import {
  apply, diaryLine, emptyRun, LOCATE_STAGES, LOOKING_FOR, pinsFor, question, spotFor, STEP_NAME, STEPS,
  type Moment, type Run, type RunEvent, type Verdicts,
} from "./runState";
import { durationText } from "./upload";

async function getJson(path: string): Promise<any> {
  const response = await fetch(path, { cache: "no-store" });
  return response.ok ? response.json() : null;
}

/** Rebuilds the run from its events and keeps following them. */
function useRun(id: string) {
  const [run, setRun] = useState<Run>(emptyRun);
  const [missing, setMissing] = useState(false);
  const [online, setOnline] = useState(true);
  useEffect(() => {
    let lastSeq = 0;
    setRun(emptyRun());
    const source = new EventSource(`/api/runs/${id}/events`);
    source.onopen = () => setOnline(true);
    source.onmessage = (m) => {
      const e: RunEvent = JSON.parse(m.data);
      if (e.seq <= lastSeq) return; // a reconnect replays the history: skip what we already have
      lastSeq = e.seq;
      setRun((r) => apply(r, e));
    };
    source.onerror = () => {
      setOnline(false);
      fetch(`/api/runs/${id}`).then((r) => { if (r.status === 404) { setMissing(true); source.close(); } });
    };
    return () => source.close();
  }, [id]);
  return { run, missing, online };
}

/** Counts up once a second; returns m:ss since `since`. */
function useTimer(since?: string, running = true) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return since ? durationText(Math.max(0, (now - Date.parse(since)) / 1000)) : "0:00";
}

/** A number that steps up every `ms` while `on`. */
function useCycle(ms: number, on: boolean) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!on) return;
    const timer = setInterval(() => setI((n) => n + 1), ms);
    return () => clearInterval(timer);
  }, [ms, on]);
  return i;
}

function viewFor(spot: Spot): number {
  const [x, y] = SPOTS[spot];
  if (y > 0.5) return VIEWS.left;
  if (y < -0.5) return VIEWS.right;
  return x < 0 ? VIEWS.rear : VIEWS.front;
}

/** The plate, its characters arriving left to right, each blurred first and then sharp (Scene 7). */
function Plate({ text }: { text: string }) {
  return (
    <p className="text-title inline-flex rounded-input border-2 border-ink bg-top px-4 py-2 font-semibold tracking-widest" aria-label={text}>
      {[...text].map((c, i) => (
        <motion.span key={i} aria-hidden initial={{ opacity: 0, filter: "blur(6px)" }} animate={{ opacity: 1, filter: "blur(0px)" }}
          transition={{ duration: 0.25, delay: i * 0.08 }}>{c}</motion.span>
      ))}
    </p>
  );
}

const chip = "text-label rounded-full bg-surface px-4 py-2 shadow-panel";

export function RunPage() {
  const { id = "" } = useParams();
  const { run, missing, online } = useRun(id);
  const [moments, setMoments] = useState<Moment[]>();
  const [verdicts, setVerdicts] = useState<Verdicts>();
  const s = run.steps;
  const [sentConfirm, setSentConfirm] = useState(false); // confirmed here; the next events are on their way

  // Moments once locate is done; verdicts once verify is done (read from the run's saved results).
  useEffect(() => {
    if (s.locate.state === "done" && !moments)
      getJson(`/api/runs/${id}/files/01_locate/response.json`).then((r) => r?.parsed?.items && setMoments(r.parsed.items));
  }, [s.locate.state, id, moments]);
  useEffect(() => {
    if (s.verify.state !== "done" || verdicts) return;
    getJson(`/api/runs/${id}/files/03_verify/response.json`).then((r) => {
      const p = r?.parsed;
      if (!p) return;
      const findings: { item_id: string; confirmed: boolean }[] = p.findings ?? [];
      const plateIds = p.plate?.source === "ocr" ? (moments ?? []).filter((m) => m.category === "plate").map((m) => m.id) : [];
      const v = p.vehicle ?? {};
      const car = ["make", "model", "variant", "year"].map((k) => v[k]?.value).filter(Boolean).join(" ");
      setVerdicts({
        confirmed: [...findings.filter((f) => f.confirmed).map((f) => f.item_id), ...plateIds],
        rejected: findings.filter((f) => !f.confirmed).map((f) => f.item_id),
        plate: p.plate?.text, km: p.odometer_km?.value ?? undefined, car: car || undefined,
      });
    });
  }, [s.verify.state, id, verdicts, moments]);

  const current = run.current;
  const step = current ? s[current] : undefined;
  const waiting = run.waiting && !sentConfirm;
  const live = !!current && !waiting && !run.ended;
  const timer = useTimer(step?.startedAt, live);
  const lookingFor = useCycle(2600, current === "locate" && /Asking/i.test(step?.progress ?? ""));
  const checkOn = live && (current === "frames" || current === "verify") && !!moments?.length;
  const checkIndex = useCycle(current === "frames" ? 700 : 1900, checkOn);
  const checking = checkOn ? moments![checkIndex % moments!.length] : undefined;
  const view = checking ? viewFor(spotFor(checking)) : waiting || run.ended ? VIEWS.front : undefined;
  const pins = useMemo(() => pinsFor(moments, verdicts), [moments, verdicts]);

  // The tab says what is happening, because people leave it during a run.
  useEffect(() => {
    document.title = waiting ? "Waiting for you — CarLens"
      : run.ended?.status === "failed" ? `Stopped at ${STEP_NAME[run.ended.failedAt ?? ""] ?? "a step"} — CarLens`
      : current ? `${STEP_NAME[current]} — CarLens` : "CarLens";
    return () => { document.title = "CarLens"; };
  }, [waiting, run.ended, current]);

  if (missing)
    return (
      <div className="flex min-h-svh items-center justify-center bg-canvas px-4 text-ink">
        <Lens scene="missing" radius={32} className="w-[min(92vw,24rem)]">
          <div className="space-y-4 p-6">
            <p className="text-heading">This run does not exist.</p>
            <Link to="/home" className="text-label inline-block rounded-full bg-canvas px-5 py-3 text-ink">Go to Home</Link>
          </div>
        </Lens>
      </div>
    );

  // --- The Lens: step pill while running, a still card when the run needs the user or has stopped ---
  let lens;
  const lastDone = [...STEPS].reverse().find((k) => s[k].state === "done");
  if (run.ended?.status === "failed") {
    const at = run.ended.failedAt ?? "";
    lens = (
      <Lens scene="failed" radius={32} tone="danger" className="w-[min(92vw,28rem)]">
        <div className="space-y-2 p-6">
          <p className="text-heading">{STEP_NAME[at] ?? "A step"} stopped.</p>
          <p className="text-small break-words opacity-90">{run.ended.error ?? s[at]?.error}</p>
          <p className="text-small opacity-90">Everything found before this step is kept. Resuming arrives in a later stage.</p>
        </div>
      </Lens>
    );
  } else if (run.ended?.status === "partial") {
    lens = (
      <Lens scene="partial" radius={32} className="w-[min(92vw,28rem)]">
        <div className="space-y-2 p-6">
          <p className="text-heading">This run stopped after {STEP_NAME[lastDone ?? ""]?.toLowerCase() ?? "a step"}.</p>
          <p className="text-body opacity-80">It was set to end there.</p>
        </div>
      </Lens>
    );
  } else if (waiting && run.confirmPayload) {
    lens = (
      <Lens scene="confirm" radius={32} className="w-full">
        <ConfirmCard runId={id} payload={run.confirmPayload as ConfirmPayload} onConfirmed={() => setSentConfirm(true)} />
      </Lens>
    );
  } else {
    lens = (
      <Lens scene={current ?? "connecting"} radius={22} spring="rubber" className="h-11">
        <div className="text-label flex h-full items-center gap-4 px-5 whitespace-nowrap">
          <span>{current && !(current === "confirm" && sentConfirm) ? STEP_NAME[current] : current ? "Details confirmed" : "Connecting"}</span>
          {current && current !== "confirm" && <span className="tabular-nums opacity-70">{timer}</span>}
        </div>
      </Lens>
    );
  }

  // --- The line under the car: what is happening right now, in plain words ---
  let stageLine = "";
  if (current === "upload") stageLine = "Checking the video";
  if (current === "locate") {
    const reached = LOCATE_STAGES.filter(([re]) => re.test(step?.progress ?? "")).pop();
    stageLine = /Asking/i.test(step?.progress ?? "") ? LOOKING_FOR[lookingFor % LOOKING_FOR.length] : reached?.[1] ?? "Getting the video ready";
  }
  if (current === "frames") {
    const m = /^(\d+) \/ (\d+)/.exec(step?.progress ?? "");
    stageLine = m ? `Checking frames around each moment, ${m[1]} of ${m[2]}` : "Checking frames around each moment";
  }
  if (current === "verify") stageLine = checking ? question(checking) : run.plate ? "Reading the plate" : "Getting the frames ready";
  if (current === "photos") stageLine = "Scoring your photos";
  if (current === "confirm" && sentConfirm) stageLine = "Starting the next step";

  const locateStage = current === "locate" ? LOCATE_STAGES.findIndex(([re]) => re.test(step?.progress ?? "")) : -1;
  const diary = STEPS.filter((k) => s[k].state === "done" || s[k].state === "skipped");

  return (
    <div className="min-h-svh bg-canvas text-ink">
      <header className="flex items-center justify-between gap-3 px-4 pt-4 sm:px-8 sm:pt-6">
        <Link to="/home" className="text-heading">CarLens</Link>
        <Link to="/home" className="text-label rounded-full px-4 py-2 text-ink-2 hover:text-ink">My runs</Link>
      </header>

      {/* The Lens stays pinned while the page scrolls. While confirm waits, the Lens is the card on the right instead. */}
      {!waiting && <div className="sticky top-0 z-10 flex min-h-20 justify-center bg-canvas/85 px-4 py-4 backdrop-blur-sm">{lens}</div>}
      {!online && !run.ended && (
        <p className="text-small text-center text-warn-text">Connection lost. Reconnecting.</p>
      )}

      <main className={`mx-auto px-4 pb-24 sm:px-8 ${waiting ? "max-w-6xl pt-4 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(22rem,28rem)] lg:items-start lg:gap-10" : "max-w-3xl"}`}>
        {/* Confirm: the card sits on the right on wide screens, above the car on phones. No scroll box around it:
            the Lens's shape animation measures wrongly inside one (the card came out stretched and clipped). */}
        {waiting && <aside className="mb-8 min-w-0 lg:order-2 lg:mb-0">{lens}</aside>}
        <div>
        <div className="relative h-[clamp(15rem,48vw,26rem)]">
          <Car3D className="absolute inset-0 h-full w-full" view={view} pins={pins} checking={checking ? spotFor(checking) : undefined}
            secondsPerTurn={live ? 24 : 60} />
        </div>

        <div className="min-h-24 text-center">
          {current === "locate" && (
            <ol className="mb-4 flex justify-center gap-2" aria-label="Progress of this step">
              {LOCATE_STAGES.map(([, label], i) => (
                <motion.li key={label} title={label} layout transition={springs.rubber}
                  className={`h-1.5 rounded-full ${i < locateStage ? "w-6 bg-ink" : i === locateStage ? "w-10 bg-ink" : "w-6 bg-line-strong"}`} />
              ))}
            </ol>
          )}
          {current === "verify" && run.plate && !verdicts && <div className="mb-4"><Plate text={run.plate} /></div>}
          <AnimatePresence mode="wait" initial={false}>
            {stageLine && !waiting && !run.ended && (
              <motion.p key={stageLine} {...swap} transition={{ duration: 0.2 }} className="text-body-l text-ink-2">{stageLine}</motion.p>
            )}
          </AnimatePresence>
          <AnimatePresence>
            {run.note && live && (
              <motion.p key={run.note} {...swap} className="text-small mx-auto mt-3 max-w-md rounded-input border border-warn-line bg-warn-soft px-4 py-2 text-warn-text">
                That AI model did not answer, so the next one is answering.
              </motion.p>
            )}
          </AnimatePresence>
        </div>

        {/* The shelf: facts the pipeline has learned (Scene 8). */}
        {verdicts && (
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {[verdicts.car, verdicts.plate, verdicts.km !== undefined ? `${verdicts.km.toLocaleString("en-IN")} km` : undefined]
              .filter(Boolean).map((fact, i) => (
                <motion.span key={fact} className={chip} initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ ...springs.settle, delay: i * 0.12 }}>{fact}</motion.span>
              ))}
          </div>
        )}

        {/* The diary: one line per finished step; it stays as the run moves on. */}
        {diary.length > 0 && (
          <ol className="mt-16 space-y-3 border-l border-line pl-5">
            {diary.map((k) => (
              <motion.li key={k} {...swap} className="text-body text-ink-2">
                <span className="text-label mr-2 text-ink">{STEP_NAME[k]}</span>{diaryLine(k, run, moments, verdicts)}
              </motion.li>
            ))}
          </ol>
        )}
        </div>
      </main>
    </div>
  );
}
