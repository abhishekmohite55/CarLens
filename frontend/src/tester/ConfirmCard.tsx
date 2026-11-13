// Stage F6: Confirm (docs/frontend/13-storyboard.md Scene 9; backend 02-design.md §4, CNF-1…11).
// The run waits here. Everything the AI found is filled in; alternatives are chips; nothing asks for a full list.
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../shared/api";
import { springs } from "./motion";

type Field = { value: any; confidence?: number | null; alternatives?: any[] } | null;
export type ConfirmPayload = {
  vehicle: Record<string, Field>;
  plate: { text?: string | null; confidence?: number | null; alternatives?: string[]; source?: string } | null;
  odometer_km: Field;
  tyres_assessed: boolean;
  odometer_found: boolean;
  city: { value: string | null; state: string | null; candidates: { code: string; city: string; state: string }[] };
  year_options: number[];
  expand: boolean;
  expand_threshold: number;
};

const SLOTS = [
  ["front_left", "Front left"], ["front_right", "Front right"], ["rear_left", "Rear left"], ["rear_right", "Rear right"],
] as const;
const input = "text-body w-full rounded-input bg-canvas px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-line-strong";
const chipBase = "text-label rounded-full px-3 py-1.5 transition-colors";
const primary = "text-label rounded-full bg-canvas px-5 py-3 text-ink disabled:opacity-50";
const quiet = "text-label rounded-full px-4 py-2 opacity-75 hover:opacity-100";

const val = (f: Field) => (f && f.value !== undefined && f.value !== null ? f.value : null);

/** One field: label, AI / edited tag, alternatives as chips, an orange outline when the AI is unsure. */
function Row({ label, ai, edited, unsure, chips, children }: {
  label: string; ai: boolean; edited: boolean; unsure?: boolean; chips?: ReactNode; children: ReactNode;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-label flex items-center gap-2">
        <span className="opacity-80">{label}</span>
        {edited ? <span className="text-small rounded-full bg-canvas/15 px-2">edited</span>
          : ai ? <span className="text-small rounded-full bg-canvas/15 px-2">AI</span> : null}
      </span>
      {chips && <span className="flex flex-wrap gap-1.5">{chips}</span>}
      <span className={`block rounded-input ${unsure ? "ring-2 ring-warn" : ""}`}>{children}</span>
      {unsure && <span className="text-small inline-block rounded-full bg-warn-soft px-3 py-1 text-warn-text">The AI is not sure about this.</span>}
    </label>
  );
}

function Chips({ options, value, onPick }: { options: any[]; value: any; onPick: (v: any) => void }) {
  return (
    <>
      {options.filter((o, i) => o !== null && o !== "" && options.indexOf(o) === i).map((o) => (
        <button key={String(o)} type="button" onClick={() => onPick(o)}
          className={`${chipBase} ${String(o) === String(value) ? "bg-canvas text-ink" : "bg-canvas/15 hover:bg-canvas/25"}`}>
          {String(o)}
        </button>
      ))}
    </>
  );
}

/** A photo slot: pick, see the thumbnail, replace or remove. Uploads as soon as it is picked (CNF-11). */
function Slot({ runId, slot, label, onChange }: { runId: string; slot: string; label: string; onChange: (has: boolean) => void }) {
  const [thumb, setThumb] = useState<string | null>(null);
  const [state, setState] = useState<"idle" | "uploading">("idle");
  const [problem, setProblem] = useState("");
  const picker = useRef<HTMLInputElement>(null);

  // After a reload, a photo already uploaded for this slot shows again.
  useEffect(() => {
    const url = `/api/runs/${runId}/files/05_photos/${slot}.jpg`;
    fetch(url, { cache: "no-store" }).then((r) => { if (r.ok) { setThumb(`${url}?t=${Date.now()}`); onChange(true); } });
  }, [runId, slot]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (file?: File) => {
    if (!file) return;
    setProblem("");
    setState("uploading");
    const form = new FormData();
    form.append("photo", file);
    const response = await fetch(`/api/runs/${runId}/photos/${slot}`, { method: "POST", body: form }).catch(() => null);
    setState("idle");
    if (response?.ok) {
      setThumb(URL.createObjectURL(file));
      onChange(true);
    } else {
      const data = await response?.json().catch(() => ({}));
      setProblem(data?.error?.message ?? "Upload failed. Try again.");
    }
  };
  const remove = async () => {
    await api(`/api/runs/${runId}/photos/${slot}`, { method: "DELETE" }).catch(() => {});
    setThumb(null);
    onChange(false);
  };

  return (
    <div className="space-y-1.5">
      <button type="button" onClick={() => picker.current?.click()} aria-label={`${label} photo`}
        className="relative grid aspect-square w-full place-items-center overflow-hidden rounded-full border-2 border-dashed border-canvas/40 hover:border-canvas/70">
        {thumb ? <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover" />
          : <span className="text-small opacity-80">{state === "uploading" ? "Uploading" : "Add photo"}</span>}
      </button>
      <p className="text-small text-center opacity-80">{label}</p>
      {thumb && <button type="button" onClick={remove} className="text-small block w-full text-center underline opacity-70">Remove</button>}
      {problem && <p className="text-small rounded-input bg-danger-soft px-2 py-1 text-center text-danger-text">{problem}</p>}
      <input ref={picker} type="file" accept="image/*" hidden onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
    </div>
  );
}

export function ConfirmCard({ runId, payload, onConfirmed }: { runId: string; payload: ConfirmPayload; onConfirmed: () => void }) {
  const v = payload.vehicle ?? {};
  const start = useMemo(() => ({
    make: val(v.make) ?? "", model: val(v.model) ?? "", variant: val(v.variant) ?? "", fuel: val(v.fuel) ?? "",
    year: val(v.year) ? String(val(v.year)) : "", plate: payload.plate?.text ?? "",
    city: payload.city?.value ?? "", state: payload.city?.state ?? "",
    km: val(payload.odometer_km) !== null ? String(val(payload.odometer_km)) : "",
  }), [payload]); // eslint-disable-line react-hooks/exhaustive-deps
  const [form, setForm] = useState(start);
  const [open, setOpen] = useState(payload.expand);
  const [photos, setPhotos] = useState<Record<string, boolean>>({});
  const [hideTyres, setHideTyres] = useState(false);
  const [hideOdo, setHideOdo] = useState(false);
  const [cities, setCities] = useState<{ city: string; state: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const set = (k: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [k]: value }));
  const unsure = (name: string) => {
    const f = v[name];
    return !val(f) || (f?.confidence ?? 0) < payload.expand_threshold;
  };
  // City type-ahead: that state's cities when the state is known, else all (the browser filters as you type).
  useEffect(() => {
    if (!open) return;
    api<{ city: string; state: string }[]>(`/api/cities${form.state ? `?state=${encodeURIComponent(form.state)}` : ""}`)
      .then(setCities).catch(() => setCities([]));
  }, [open, form.state]);

  const summary = [form.make, form.model, form.variant, form.year].filter(Boolean).join(" ")
    + [form.fuel, form.city, form.km ? `${Number(form.km).toLocaleString("en-IN")} km` : ""].filter(Boolean).map((x) => `, ${x}`).join("");
  const ready = form.make.trim() && form.model.trim();
  const tyrePhotos = SLOTS.some(([slot]) => photos[slot]);

  const confirm = async () => {
    setBusy(true);
    setProblem("");
    const skipped: string[] = [];
    if (!payload.tyres_assessed && !tyrePhotos) skipped.push("tyre_photo");
    if (!payload.odometer_found && !form.km && !photos.odometer) skipped.push("odometer");
    try {
      await api(`/api/runs/${runId}/confirm`, {
        method: "POST",
        body: {
          car: { make: form.make.trim(), model: form.model.trim(), variant: form.variant.trim() || null,
            year: form.year ? Number(form.year) : null, fuel: form.fuel.trim() || null },
          plate: form.plate.trim() || null, city: form.city.trim() || null, state: form.state || null,
          odometer_km: form.km ? Math.round(Number(form.km)) : null, skipped,
        },
      });
      onConfirmed();
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not confirm. Try again.");
      setBusy(false);
    }
  };

  const text = (k: "make" | "model" | "variant" | "fuel", label: string, required = false) => (
    <Row label={label} ai={!!start[k]} edited={form[k] !== start[k]} unsure={k !== "variant" && k !== "fuel" && unsure(k)}
      chips={<Chips options={[val(v[k]), ...(v[k]?.alternatives ?? [])]} value={form[k]} onPick={(o) => set(k)(String(o))} />}>
      <input className={input} value={form[k]} required={required} onChange={(e) => set(k)(e.target.value)}
        placeholder={k === "variant" ? "Leave empty if you are not sure" : undefined} />
    </Row>
  );

  return (
    <div className="space-y-4 p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <p className="text-heading">{open ? "Check the details" : "Is this your car?"}</p>
        {/* Close the form again without confirming; the values typed so far are kept. */}
        {open && <button type="button" onClick={() => setOpen(false)} className="text-label shrink-0 rounded-full bg-canvas/15 px-3 py-1.5 hover:bg-canvas/25">Show less</button>}
      </div>
      {!open && <p className="text-body opacity-90">{summary || "The AI could not tell which car this is."}</p>}

      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
            transition={springs.rubber} className="space-y-3 overflow-hidden">
            <p className="text-small opacity-75">Values from the AI are marked AI. Change anything that is wrong.</p>
            {text("make", "Make", true)}
            {text("model", "Model", true)}
            {text("variant", "Variant (optional)")}
            <Row label="Year" ai={!!start.year} edited={form.year !== start.year} unsure={unsure("year")}
              chips={<Chips options={[val(v.year), ...(v.year?.alternatives ?? [])]} value={form.year} onPick={(o) => set("year")(String(o))} />}>
              <select className={input} value={form.year} onChange={(e) => set("year")(e.target.value)}>
                <option value="">Not sure</option>
                {payload.year_options.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </Row>
            {text("fuel", "Fuel")}
            <Row label={`Plate${payload.plate?.source ? ` (read by ${payload.plate.source === "ocr" ? "OCR" : "AI"})` : ""}`}
              ai={!!start.plate} edited={form.plate !== start.plate}
              chips={<Chips options={payload.plate?.alternatives ?? []} value={form.plate} onPick={(o) => set("plate")(String(o))} />}>
              <input className={`${input} uppercase`} value={form.plate} onChange={(e) => set("plate")(e.target.value.toUpperCase())} />
            </Row>
            <Row label="City" ai={!!start.city} edited={form.city !== start.city}
              chips={payload.city?.candidates.length > 1 && payload.city.candidates.length <= 8 ? payload.city.candidates.map((c) => (
                <button key={c.code} type="button" onClick={() => setForm((f) => ({ ...f, city: c.city, state: c.state }))}
                  className={`${chipBase} ${form.city === c.city ? "bg-canvas text-ink" : "bg-canvas/15 hover:bg-canvas/25"}`}>
                  {c.code} {c.city}
                </button>
              )) : undefined}>
              <input className={input} list="carlens-cities" value={form.city} placeholder="Type 2 letters"
                onChange={(e) => {
                  const typed = e.target.value;
                  const match = cities.find((c) => c.city === typed);
                  setForm((f) => ({ ...f, city: typed, state: match ? match.state : f.state }));
                }} />
              <datalist id="carlens-cities">
                {form.city.length >= 2 && cities.filter((c) => c.city.toLowerCase().includes(form.city.toLowerCase())).slice(0, 30)
                  .map((c) => <option key={`${c.city}-${c.state}`} value={c.city}>{c.state}</option>)}
              </datalist>
            </Row>
            {payload.odometer_found && (
              <Row label="Odometer km" ai={!!start.km} edited={form.km !== start.km}>
                <input className={`${input} tabular-nums`} inputMode="numeric" value={form.km}
                  onChange={(e) => set("km")(e.target.value.replace(/\D/g, ""))} />
              </Row>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Only what the video missed is asked (CNF-7, CNF-8). Skipping never blocks the run. */}
      {!payload.tyres_assessed && !hideTyres && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-input bg-warn-soft px-4 py-3 text-warn-text">
          <p className="text-small">Tyres were not visible in the video. Add photos below for a better report, or skip.</p>
          <button type="button" onClick={() => setHideTyres(true)} className="text-label underline">Skip tyres</button>
        </div>
      )}
      {!payload.odometer_found && !hideOdo && (
        <div className="space-y-2 rounded-input bg-warn-soft px-4 py-3 text-warn-text">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-small">The odometer was not visible. Type the km, add a photo below, or skip.</p>
            <button type="button" onClick={() => setHideOdo(true)} className="text-label underline">Skip</button>
          </div>
          <input className={`${input} tabular-nums`} inputMode="numeric" placeholder="Odometer km" value={form.km}
            onChange={(e) => set("km")(e.target.value.replace(/\D/g, ""))} />
        </div>
      )}

      <div>
        <p className="text-label opacity-80">Tyre photos (optional)</p>
        {/* Laid out like the car: front pair above the rear pair. */}
        <div className="mt-3 grid grid-cols-2 gap-x-10 gap-y-3 px-4 sm:grid-cols-4 sm:gap-x-4 sm:px-0">
          {SLOTS.map(([slot, label]) => (
            <Slot key={slot} runId={runId} slot={slot} label={label} onChange={(has) => setPhotos((p) => ({ ...p, [slot]: has }))} />
          ))}
        </div>
        {!payload.odometer_found && (
          <div className="mx-auto mt-4 w-28">
            <Slot runId={runId} slot="odometer" label="Odometer" onChange={(has) => setPhotos((p) => ({ ...p, odometer: has }))} />
          </div>
        )}
      </div>

      {problem && <p role="alert" className="text-body rounded-input bg-danger-soft px-4 py-3 text-danger-text">{problem}</p>}
      {!ready && <p className="text-small inline-block rounded-full bg-warn-soft px-3 py-1 text-warn-text">Add make and model to continue.</p>}
      <div className="flex flex-wrap gap-2">
        <motion.button layout transition={springs.rubber} type="button" onClick={confirm} disabled={!ready || busy} className={primary}>
          {busy ? "Confirming" : "Confirm details"}
        </motion.button>
        {!open && <button type="button" onClick={() => setOpen(true)} className={quiet}>Edit details</button>}
      </div>
    </div>
  );
}
