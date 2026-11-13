// The run as the tester sees it, rebuilt from the run's events (GET /api/runs/{id}/events replays them, then streams).
// No Sent / Received for testers (owner, 14 Nov): only steps, their state and plain sentences.
import type { CarPin } from "./Car3D";
import type { Spot } from "./car";

export type RunEvent = { seq: number; ts: string; node: string; type: string; data?: Record<string, any> };
export type StepState = "waiting" | "running" | "done" | "failed" | "skipped";

export const STEPS = ["upload", "locate", "frames", "verify", "confirm", "photos", "plan", "search", "extract", "pricing", "report"];

export const STEP_NAME: Record<string, string> = {
  upload: "Checking video", locate: "Finding moments", frames: "Picking sharpest frames", verify: "Verifying",
  confirm: "Confirm details", photos: "Reading your photos", plan: "Planning searches", search: "Searching the web",
  extract: "Reading prices", pricing: "Working out the price", report: "Report",
};

export type Run = {
  steps: Record<string, { state: StepState; startedAt?: string; summary?: string; error?: string; progress?: string }>;
  current?: string; // the step running now
  note?: string; // latest model-switch note (orange)
  plate?: string; // read by OCR, shown as it arrives
  waiting: boolean; // paused at confirm
  confirmPayload?: Record<string, any>; // what the confirm card shows (awaiting_confirm event)
  ended?: { status: string; failedAt?: string; error?: string };
};

export const emptyRun = (): Run => ({ steps: Object.fromEntries(STEPS.map((s) => [s, { state: "waiting" }])), waiting: false });

/** Applies one event. Pure, so a reload rebuilds the same picture from the replayed events. */
export function apply(run: Run, e: RunEvent): Run {
  const steps = { ...run.steps };
  const step = steps[e.node];
  const d = e.data ?? {};
  const next: Run = { ...run, steps };
  if (e.type === "node_started" && step) {
    steps[e.node] = { state: "running", startedAt: e.ts };
    Object.assign(next, { current: e.node, note: undefined, ended: undefined, waiting: false });
  } else if (e.type === "node_progress" && step) {
    steps[e.node] = { ...step, progress: d.message };
    const msg: string = d.message ?? "";
    if (/busy|failed|no answer|Trying/i.test(msg)) next.note = msg;
    const plate = /^Plate by OCR: (\S+)/.exec(msg);
    if (plate) next.plate = plate[1];
  } else if (e.type === "node_done" && step) {
    steps[e.node] = { ...step, state: "done", summary: d.summary };
  } else if (e.type === "node_failed" && step) {
    steps[e.node] = { ...step, state: "failed", error: d.error };
  } else if (e.type === "node_skipped" && step) {
    steps[e.node] = { ...step, state: "skipped", summary: d.reason };
  } else if (e.type === "awaiting_confirm") {
    steps.confirm = { state: "running", startedAt: e.ts };
    Object.assign(next, { current: "confirm", waiting: true, confirmPayload: d });
  } else if (e.type === "run_done") {
    next.ended = { status: d.status, failedAt: d.failed_at, error: d.error };
    next.current = undefined;
    next.waiting = false;
  }
  return next;
}

/** One sentence per finished step, in the tester's words (the diary). */
export function diaryLine(step: string, run: Run, moments?: Moment[], verdicts?: Verdicts, extra?: Record<string, string>): string {
  const s = run.steps[step];
  if (extra?.[step] && s.state === "done") return extra[step];
  if (s.state === "skipped") return `${STEP_NAME[step]}: skipped.`;
  if (step === "upload") return `Video accepted: ${s.summary ?? ""}.`;
  if (step === "locate") return moments ? `Found ${moments.length} moments in the video.` : "Found the moments in the video.";
  if (step === "frames") return "Kept the sharpest frame of each moment.";
  if (step === "confirm") return "Details confirmed.";
  if (step === "photos") return "Your photos were read.";
  if (step === "verify" && verdicts) {
    const rejected = verdicts.rejected.length;
    return `Confirmed ${verdicts.confirmed.length} ${verdicts.confirmed.length === 1 ? "finding" : "findings"}` +
      (rejected ? `, rejected ${rejected} as reflection or dirt.` : ".");
  }
  return `${STEP_NAME[step]}: done.`;
}

// --- Moments (locate items) and where they sit on the car -----------------------------------------------------------

export type Moment = { id: string; category: string; label: string; side: string };
export type Verdicts = { confirmed: string[]; rejected: string[]; plate?: string; km?: number; car?: string };

/** Pins sit by side and type, not at a measured spot (Gemini gives only a time and a side). */
export function spotFor(m: Moment): Spot {
  const side = m.side, label = m.label.toLowerCase();
  const rear = label.includes("rear") || side === "rear";
  switch (m.category) {
    case "plate": return side === "front" ? "plate_front" : "plate";
    case "model_badge": return "badge";
    case "odometer": return "dashboard";
    case "windshield": return "windshield";
    case "mirror": return side === "right" ? "mirror_right" : "mirror_left";
    case "tyre":
      if (side === "right") return rear ? "tyre_rear_right" : "tyre_front_right";
      return rear ? "tyre_rear_left" : "tyre_front_left";
    default: // damage
      if (side === "front") return "bumper_front";
      if (side === "rear") return "bumper_rear";
      if (side === "right") return rear ? "door_right_rear" : "door_right_front";
      if (side === "left") return rear ? "door_left_rear" : "door_left_front";
      return side === "interior" ? "dashboard" : "windshield";
  }
}

export function pinsFor(moments: Moment[] | undefined, verdicts?: Verdicts): CarPin[] {
  return (moments ?? []).map((m) => ({
    spot: spotFor(m),
    solid: verdicts?.confirmed.includes(m.id),
    faded: verdicts?.rejected.includes(m.id),
  }));
}

/** The question the AI is asked about each kind of moment (Scene 8). */
export function question(m: Moment): string {
  return {
    plate: "What does the plate say?",
    model_badge: "What does the badge say?",
    odometer: "What does the odometer read?",
    tyre: "How worn is this tyre?",
    mirror: "Is this mirror damaged?",
    windshield: "Any cracks in the windshield?",
  }[m.category] ?? "Real damage, or a reflection?";
}

/** While Gemini watches the video (Scene 5). */
export const LOOKING_FOR = [
  "Looking for the number plate", "Looking for the rear badge", "Looking for the odometer",
  "Looking for each tyre", "Looking for dents, scratches and cracks", "Noting which sides of the car are shown",
];

/** Locate's real sub-steps, in order, matched against its progress messages. */
export const LOCATE_STAGES: [RegExp, string][] = [
  [/Shrinking/i, "Making a lighter copy for the AI"],
  [/Uploading/i, "Sending the video to Gemini"],
  [/processing/i, "Gemini is processing the video"],
  [/Asking/i, "Gemini is watching the video"],
];
