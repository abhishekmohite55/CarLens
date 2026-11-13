// Stage F1 test page: the look, the Lens and the car, to be checked by the owner on a laptop and a phone.
// Later stages replace this page with the real screens; Lens, Car3D, theme and tester.css stay.
import { useState, type ReactNode } from "react";
import { Car3D } from "./Car3D";
import { Lens, type LensTone } from "./Lens";
import type { SpringName } from "./motion";
import { ThemeToggle } from "./theme";

type LensState = { name: string; radius: number; tone?: LensTone; spring?: SpringName; className: string; content: ReactNode };

const chip = "text-label rounded-full bg-canvas px-4 py-2 text-ink";

const LENS_STATES: LensState[] = [
  { name: "Dot", radius: 8, className: "h-4 w-4", content: null },
  { name: "Pill", radius: 28, spring: "rubber", className: "h-14",
    content: <div className="text-label flex h-full items-center px-7">CarLens</div> },
  { name: "Upload pill", radius: 32, spring: "rubber", className: "h-16",
    content: (
      <div className="text-label flex h-full items-center gap-4 pr-3 pl-7">
        <span className="whitespace-nowrap">Drop a walkaround video</span>
        <span className={`${chip} whitespace-nowrap`}>Choose video</span>
      </div>
    ) },
  { name: "Upload bar", radius: 7, tone: "track", className: "h-3.5 w-[min(80vw,22rem)]",
    content: <div className="h-full w-[42%] rounded-full bg-ink" /> },
  { name: "Step pill", radius: 22, spring: "rubber", className: "h-11",
    content: (
      <div className="text-label flex h-full items-center gap-4 px-5 whitespace-nowrap">
        <span>Finding moments</span>
        <span className="tabular-nums opacity-70">0:42</span>
      </div>
    ) },
  { name: "Confirm card", radius: 32, className: "w-[min(92vw,24rem)]",
    content: (
      <div className="p-6">
        <p className="text-title">Is this your car?</p>
        <p className="text-body mt-3 opacity-80">Maruti Suzuki Ertiga VXi CNG 2020, Pimpri-Chinchwad, 1,10,422 km</p>
        <p className={`${chip} mt-6 inline-block`}>Confirm details</p>
      </div>
    ) },
  { name: "Price card", radius: 32, className: "w-[min(92vw,34rem)]",
    content: (
      <div className="p-6 sm:p-8">
        <p className="text-label opacity-70">Maruti Suzuki Ertiga ZXi 2023, Petrol</p>
        <p className="text-display mt-3 tabular-nums">₹10,60,000 to ₹10,71,000</p>
        <p className="text-body mt-4 opacity-80">Fair value after repairs, from 4 listings and 5 new-price sources.</p>
      </div>
    ) },
  { name: "Stopped", radius: 32, tone: "danger", className: "w-[min(92vw,24rem)]",
    content: (
      <div className="p-6">
        <p className="text-heading">Verify stopped</p>
        <p className="text-body mt-2">All four models failed. Steps before Verify are kept, so resuming is free.</p>
        <p className={`${chip} mt-5 inline-block`}>Resume from Verify</p>
      </div>
    ) },
];

const NEUTRALS = ["canvas", "deep", "surface", "top", "line", "line-strong", "ink-3", "ink-2", "ink"];
const STATUSES = [
  { name: "Danger", key: "danger", sample: "Verify stopped" },
  { name: "Warning", key: "warn", sample: "gemini-3.8-flash is busy. Asking the next model." },
  { name: "Positive", key: "ok", sample: "Kept: ₹4,95,000" },
];
const TYPE = [
  { name: "Display", className: "text-display", sample: "₹10,60,000" },
  { name: "Title", className: "text-title", sample: "Is this your car?" },
  { name: "Heading", className: "text-heading", sample: "Damage found" },
  { name: "Body large", className: "text-body-l", sample: "Looking for dents, scratches and cracks" },
  { name: "Body", className: "text-body", sample: "Found 12 moments. Not seen: right side." },
  { name: "Label", className: "text-label", sample: "Confirm details" },
  { name: "Small", className: "text-small", sample: "r_20261105_083146_81b6" },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-24">
      <h2 className="text-heading">{title}</h2>
      <div className="mt-6">{children}</div>
    </section>
  );
}

export function TestPage() {
  const [index, setIndex] = useState(1);
  const state = LENS_STATES[index];
  return (
    <div className="mx-auto max-w-5xl px-4 pt-6 pb-32 sm:px-8">
      <header className="flex items-center justify-between">
        <span className="text-heading">CarLens</span>
        <ThemeToggle />
      </header>

      <Section title="The Lens">
        {/* Fixed height, so the page below does not move while the Lens changes shape. */}
        <div className="flex h-[26rem] items-center justify-center">
          <Lens scene={state.name} radius={state.radius} tone={state.tone} spring={state.spring} className={state.className}>
            {state.content}
          </Lens>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {LENS_STATES.map((item, i) => (
            <button key={item.name} onClick={() => setIndex(i)} aria-pressed={i === index}
              className={`text-label rounded-full border px-4 py-2 ${i === index ? "border-ink bg-ink text-canvas" : "border-line-strong text-ink-2 hover:text-ink"}`}>
              {item.name}
            </button>
          ))}
        </div>
      </Section>

      <Section title="The car">
        <Car3D className="h-[clamp(16rem,50vw,30rem)] w-full" />
      </Section>

      <Section title="Neutral shades">
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-9">
          {NEUTRALS.map((name) => (
            <div key={name}>
              <div className="h-16 rounded-panel border border-line" style={{ backgroundColor: `var(--c-${name})` }} />
              <p className="text-small mt-2 text-ink-3">{name}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Status shades">
        <div className="grid gap-4 sm:grid-cols-3">
          {STATUSES.map(({ name, key, sample }) => (
            <div key={key} className="rounded-panel border p-4"
              style={{ backgroundColor: `var(--c-${key}-soft)`, borderColor: `var(--c-${key}-line)` }}>
              <p className="text-label flex items-center gap-2" style={{ color: `var(--c-${key}-text)` }}>
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: `var(--c-${key})` }} />
                {name}
              </p>
              <p className="text-body mt-2" style={{ color: `var(--c-${key}-text)` }}>{sample}</p>
              <p className="text-label mt-4 inline-block rounded-full px-4 py-2 text-on-status" style={{ backgroundColor: `var(--c-${key})` }}>
                Label on solid
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type">
        <div className="space-y-6">
          {TYPE.map(({ name, className, sample }) => (
            <div key={name}>
              <p className="text-small text-ink-3">{name}</p>
              <p className={`${className} tabular-nums`}>{sample}</p>
            </div>
          ))}
          <p className="text-body text-ink-2">Secondary text (ink 2)</p>
          <p className="text-body text-ink-3">Quiet text (ink 3)</p>
        </div>
      </Section>

      <Section title="Curves and shadows">
        <div className="flex flex-wrap items-end gap-6">
          <div className="text-small rounded-chip bg-surface px-4 py-3 shadow-panel">Chip, 8</div>
          <div className="text-small rounded-input bg-top px-5 py-4 shadow-panel">Input, 14</div>
          <div className="text-small rounded-panel bg-surface px-6 py-8 shadow-panel">Panel, 22</div>
          <div className="text-small rounded-lens bg-ink px-8 py-10 text-canvas shadow-lens">Lens card, 32</div>
        </div>
      </Section>
    </div>
  );
}
