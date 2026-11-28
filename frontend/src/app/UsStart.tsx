// US first screen (docs/backend/07-us-market.md §5): VIN → car card (Yes / Change VIN) → state → miles.
// The upload is unlocked only after Yes on the car and valid miles; the server uses its saved lookup, never these values.
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../shared/api";
import { normaliseVin, parseMiles, vinProblem, type UsConfig } from "./market";
import { springs, swap } from "./motion";

export type UsFields = { vin: string; state: string; miles: number };
type Car = { year?: number; make?: string; model?: string; variant?: string; body?: string; engine?: string; fuel?: string; drive?: string };
type Lookup = { vin: string; car: Car; provider?: string };

const STATE_KEY = "carlens.app.state";
const card = "rounded-panel bg-surface shadow-panel";
const field = "text-body w-full rounded-input border border-line bg-canvas px-4 py-3 outline-none focus:border-ink";
const chipBase = "text-small rounded-full px-3 py-1.5 transition-colors";

const LOOKUP_WORDS: Record<string, string> = {
  vin_not_found: "We could not find a car for this VIN. Check it and try again.",
  too_many: "Too many VIN lookups in the last hour. Try again later.",
  vin_unavailable: "The VIN service is not answering right now. Come back later: no run was used.",
  market_off: "US inspections are closed right now.",
};

export function UsStart({ config, disabled, onReady }: { config: UsConfig; disabled?: boolean; onReady: (f: UsFields | null) => void }) {
  const [vinText, setVinText] = useState("");
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [looking, setLooking] = useState(false);
  const [lookupProblem, setLookupProblem] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [state, setState] = useState<string>(() => {
    try { return localStorage.getItem(STATE_KEY) ?? config.state_guess ?? ""; } catch { return config.state_guess ?? ""; }
  });
  const [stateText, setStateText] = useState(() => config.states.find((x) => x.code === state)?.name ?? "");
  const [milesText, setMilesText] = useState("");
  const asked = useRef("");

  const vin = normaliseVin(vinText);
  const problem = vin ? vinProblem(vin) : "";
  const miles = parseMiles(milesText);
  const name = (code: string) => config.states.find((s) => s.code === code)?.name ?? code;

  // The lookup fires by itself once the VIN is valid (once per VIN).
  useEffect(() => {
    if (!vin || problem || asked.current === vin) return;
    asked.current = vin;
    setLooking(true);
    setLookupProblem("");
    api<Lookup>("/api/vin/lookup", { method: "POST", body: { vin } })
      .then((answer) => setLookup(answer))
      .catch((e) => setLookupProblem(e instanceof ApiError ? LOOKUP_WORDS[e.code] ?? e.message : "The server did not answer."))
      .finally(() => setLooking(false));
  }, [vin, problem]);

  useEffect(() => {
    try { localStorage.setItem(STATE_KEY, state); } catch { /* private mode */ }
  }, [state]);

  useEffect(() => {
    onReady(confirmed && lookup && lookup.vin === vin && miles !== null && miles > 0 ? { vin, state, miles } : null);
  }, [confirmed, lookup, vin, state, miles, onReady]);

  const changeVin = () => {
    setLookup(null);
    setConfirmed(false);
    setVinText("");
    asked.current = "";
  };
  // The field always shows the chosen state's name (fix 28 Nov: it used to empty itself after a pick).
  const choose = (code: string) => { setState(code); setStateText(code ? name(code) : ""); };
  const pickTyped = (text: string) => {
    setStateText(text);
    const t = text.trim().toLowerCase();
    const hit = config.states.find((s) => s.code.toLowerCase() === t || s.name.toLowerCase() === t);
    if (hit) { setState(hit.code); setStateText(hit.name); }
    else if (!t) setState("");
  };
  const c = lookup?.car;
  const carLine = c ? [c.year, c.make, c.model].filter(Boolean).join(" ") : "";

  return (
    <div className={`w-[min(92vw,30rem)] space-y-5 ${disabled ? "pointer-events-none opacity-50" : ""}`}>
      {/* 1. VIN */}
      <div className="space-y-2">
        <label htmlFor="us-vin" className="text-label">Your car's VIN</label>
        <input id="us-vin" value={vinText} onChange={(e) => { setVinText(e.target.value); setConfirmed(false); }}
          maxLength={24} autoComplete="off" spellCheck={false} placeholder="17 letters and numbers"
          className={`${field} font-medium tracking-widest uppercase`} />
        <p className={`text-small ${!vin ? "text-ink-3" : problem ? (vin.length < 17 ? "text-warn-text" : "text-danger-text") : "text-ok-text"}`}>
          {!vin ? "On the dashboard by the windshield, or on the driver's door frame." : problem || (looking ? "Looking up your car…" : "Valid VIN.")}
        </p>
        {lookupProblem && <p role="alert" className="text-small rounded-input bg-danger-soft px-3 py-2 text-danger-text">{lookupProblem}</p>}
      </div>

      {/* 2. The car card */}
      <AnimatePresence>
        {c && lookup?.vin === vin && (
          <motion.div key={lookup.vin} {...swap} transition={springs.settle} className={`${card} space-y-3 px-5 py-4`}>
            <p className="text-small text-ink-3">Is this your car?</p>
            <p className="text-heading">{carLine}{c.variant ? ` ${c.variant}` : ""}</p>
            <p className="text-small text-ink-2">{[c.body, c.engine, c.fuel, c.drive].filter(Boolean).join(" · ")}</p>
            {confirmed ? (
              <p className="text-small flex items-center gap-3 text-ok-text">Car confirmed.
                <button onClick={changeVin} className="text-ink-2 underline underline-offset-4">Change VIN</button></p>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button onClick={() => setConfirmed(true)} className="text-label rounded-full bg-ink px-5 py-2.5 text-canvas">Yes, that's my car</button>
                <button onClick={changeVin} className="text-label rounded-full px-4 py-2.5 text-ink-2 hover:text-ink">Change VIN</button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 3. State and 4. miles, once the car is confirmed */}
      <AnimatePresence>
        {confirmed && (
          <motion.div key="details" {...swap} transition={springs.settle} className="space-y-5">
            <div className="space-y-2">
              <p className="text-label">State <span className="text-small text-ink-3">(for local prices; optional)</span></p>
              <div className="flex flex-wrap gap-1.5">
                {config.top_states.map((code) => (
                  <button key={code} onClick={() => choose(state === code ? "" : code)} title={name(code)}
                    className={`${chipBase} ${state === code ? "bg-ink text-canvas" : "bg-surface text-ink-2 shadow-panel hover:text-ink"}`}>{code}</button>
                ))}
              </div>
              <input list="us-states" value={stateText} onChange={(e) => pickTyped(e.target.value)} placeholder="Type a state's name"
                className={field} autoComplete="off" />
              <datalist id="us-states">{config.states.map((s) => <option key={s.code} value={s.name} />)}</datalist>
              <p className="text-small text-ink-3">
                {state ? <>Prices for <b className="text-ink">{name(state)}</b> and the whole US. <button onClick={() => choose("")}
                  className="underline underline-offset-4">Clear</button></> : "No state: US-wide prices only."}
              </p>
            </div>
            <div className="space-y-2">
              <label htmlFor="us-miles" className="text-label">Miles on the odometer</label>
              <input id="us-miles" value={milesText} onChange={(e) => setMilesText(e.target.value)} inputMode="numeric"
                placeholder="e.g. 48,200" autoComplete="off" className={`${field} tabular-nums`} />
              {milesText && miles === null && <p className="text-small text-danger-text">Digits only (commas are fine), e.g. 48,200.</p>}
              {miles !== null && <p className="text-small text-ink-3">{miles.toLocaleString("en-US")} miles</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
