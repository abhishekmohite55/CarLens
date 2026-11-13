// Stage F2: the landing page (docs/frontend/13-storyboard.md, Scene 1; copy from 10-site-content.md §4).
// One tall scroll area with a pinned frame: the Lens on top, the car in the middle, the chapter text below.
// Scrolling moves through the chapters; the car and the Lens answer the scroll, so no scroll is dead.
import { AnimatePresence, motion, useMotionValueEvent, useReducedMotion, useScroll } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Car3D, type CarPin } from "./Car3D";
import { VIEWS } from "./car";
import { Lens } from "./Lens";
import { springs, swap } from "./motion";
import { RollingNumber } from "./RollingNumber";
import { ThemeToggle } from "./theme";

type Chapter = {
  id: string;
  title: string;
  text: string;
  view?: number;
  pins?: CarPin[];
  checking?: CarPin["spot"];
};

const FOUND: CarPin[] = [{ spot: "plate" }, { spot: "tyre_rear_left" }, { spot: "door_left_rear" }];

const CHAPTERS: Chapter[] = [
  { id: "hero", title: "Film a used car. Get a price you can check.",
    text: "CarLens watches a walkaround video, finds the plate, odometer, tyres and damage, then searches today's listings for a price range in rupees. Every step shows its work." },
  { id: "looks", title: "It looks", view: VIEWS.rear, pins: FOUND,
    text: "AI watches the video and marks the moments that matter: the plate, the badge, the odometer, each tyre, every dent." },
  { id: "checks", title: "It checks", view: VIEWS.left, checking: "door_left_rear",
    pins: [{ spot: "plate", solid: true }, { spot: "tyre_rear_left", solid: true }, { spot: "door_left_rear", solid: true }],
    text: "The sharpest frame of each moment goes to a second AI that confirms what is real and rejects reflections and dirt. You confirm the car details." },
  { id: "prices", title: "It prices", view: VIEWS.front,
    pins: [{ spot: "plate", solid: true }, { spot: "tyre_rear_left", solid: true }, { spot: "door_left_rear", solid: true }],
    text: "CarLens searches today's new and used prices for your car, keeps only figures it can quote from a source, and works out the range with plain arithmetic." },
  { id: "hidden", title: "Nothing hidden", view: VIEWS.front,
    text: "Open any step to see exactly what was sent to the AI and what came back, down to the raw JSON. Every price links to the page it came from." },
  { id: "end", title: "Try it on your own car",
    text: "Request access. Once the owner approves you, you can run your own inspections." },
];

const SAMPLE_SENT = `{ "model": "gemini-3.8-flash",
  "frames": ["L4_damage_75.0s.jpg", "+ 9 more"],
  "ask": "Real dent, or a reflection?" }`;
const SAMPLE_RECEIVED = `{ "id": "L4", "confirmed": true,
  "part": "rear left door", "issue": "dent",
  "severity": "minor", "action": "repair" }`;

/** Intro (Scene 1, frames 1–5): dot → pill "CarLens" → car draws in → headline → actions. */
function useIntro() {
  const reduce = useReducedMotion();
  const [phase, setPhase] = useState(reduce ? 3 : 0);
  useEffect(() => {
    if (reduce) return;
    const timers = [450, 900, 2300].map((ms, i) => setTimeout(() => setPhase(i + 1), ms));
    return () => timers.forEach(clearTimeout);
  }, [reduce]);
  return phase;
}

function Actions() {
  return (
    <div className="text-label flex h-full items-center gap-1 p-1.5">
      <Link to="/request-access" className="rounded-full bg-canvas px-5 py-3 whitespace-nowrap text-ink">Request access</Link>
      <Link to="/sign-in" className="rounded-full px-5 py-3 whitespace-nowrap hover:opacity-80">Sign in</Link>
    </div>
  );
}

function LensFor({ chapter, phase }: { chapter: Chapter; phase: number }) {
  if (chapter.id === "hero" && phase === 0) return <Lens scene="dot" radius={8} className="h-4 w-4" />;
  if (chapter.id === "hero" && phase < 3)
    return (
      <Lens scene="name" radius={28} spring="rubber" className="h-14">
        <div className="text-label flex h-full items-center px-7">CarLens</div>
      </Lens>
    );
  if (chapter.id === "hero" || chapter.id === "end")
    return <Lens scene="actions" radius={30} spring="rubber" className="h-[3.75rem]"><Actions /></Lens>;
  if (chapter.id === "prices")
    return (
      <Lens scene="price" radius={32} className="w-[min(92vw,34rem)]">
        <div className="p-5 sm:p-7">
          <p className="text-small opacity-70">Example: Maruti Suzuki Ertiga ZXi 2023, Petrol</p>
          <p className="text-title mt-3"><RollingNumber text="₹10,60,000 to ₹10,71,000" /></p>
          <p className="text-small mt-3 opacity-70">Fair value after repairs, from 4 listings and 5 new-price sources.</p>
        </div>
      </Lens>
    );
  if (chapter.id === "hidden")
    return (
      <Lens scene="panel" radius={32} className="w-[min(92vw,40rem)]">
        <div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6">
          {[["Sent", SAMPLE_SENT], ["Received", SAMPLE_RECEIVED]].map(([label, json]) => (
            <div key={label}>
              <p className="text-label opacity-70">{label}</p>
              <pre className="text-small mt-2 overflow-hidden rounded-input bg-canvas/10 p-3 font-mono whitespace-pre-wrap">{json}</pre>
            </div>
          ))}
        </div>
      </Lens>
    );
  return (
    <Lens scene={chapter.id} radius={22} spring="rubber" className="h-11">
      <div className="text-label flex h-full items-center px-5 whitespace-nowrap">{chapter.title}</div>
    </Lens>
  );
}

function Headline({ text, animate }: { text: string; animate: boolean }) {
  if (!animate) return <>{text}</>;
  return (
    <>
      {text.split(" ").map((word, i) => (
        <motion.span key={i} className="inline-block whitespace-pre" initial={{ opacity: 0, filter: "blur(6px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }} transition={{ duration: 0.3, delay: i * 0.08 }}>
          {word + " "}
        </motion.span>
      ))}
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mx-auto max-w-2xl px-4 py-24 sm:px-8">
      <h2 className="text-heading">{title}</h2>
      <div className="text-body-l mt-4 text-ink-2">{children}</div>
    </section>
  );
}

export function Landing() {
  const story = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(0);
  const phase = useIntro();
  const { scrollYProgress } = useScroll({ target: story, offset: ["start start", "end end"] });
  useMotionValueEvent(scrollYProgress, "change", (v) => setIndex(Math.min(CHAPTERS.length - 1, Math.floor(v * CHAPTERS.length))));
  const chapter = CHAPTERS[index];
  const toChapter = (i: number) => {
    const top = story.current!.offsetTop + (story.current!.offsetHeight - window.innerHeight) * (i / (CHAPTERS.length - 1));
    window.scrollTo({ top, behavior: "smooth" });
  };

  return (
    <div className="bg-canvas text-ink">
      {/* One screen-height per chapter; the frame inside stays pinned while the page scrolls. */}
      <div ref={story} style={{ height: `${CHAPTERS.length * 100}svh` }}>
        <div className="sticky top-0 flex h-svh flex-col">
          <header className="flex items-center justify-between gap-3 px-4 pt-4 sm:px-8 sm:pt-6">
            <Link to="/" className="text-heading" onClick={() => toChapter(0)}>CarLens</Link>
            <nav className="text-label flex items-center gap-1 sm:gap-2">
              <button onClick={() => toChapter(1)} className="hidden rounded-full px-4 py-2 text-ink-2 hover:text-ink sm:block">How it works</button>
              <Link to="/sign-in" className="rounded-full px-4 py-2 text-ink-2 hover:text-ink">Sign in</Link>
              <ThemeToggle />
            </nav>
          </header>

          <div className="flex min-h-24 items-center justify-center px-4 pt-6">
            <LensFor chapter={chapter} phase={phase} />
          </div>

          <div className="relative min-h-0 flex-1">
            {phase >= 2 && (
              <Car3D className="absolute inset-0 h-full w-full" view={chapter.view} pins={chapter.pins} checking={chapter.checking} />
            )}
          </div>

          <div className="mx-auto w-full max-w-2xl px-4 pb-10 text-center sm:px-8 sm:pb-14">
            <AnimatePresence mode="wait" initial={false}>
              {(chapter.id !== "hero" || phase >= 2) && (
                <motion.div key={chapter.id} {...swap} transition={{ duration: 0.2 }}>
                  <h1 className={chapter.id === "hero" ? "text-title" : "text-heading"}>
                    <Headline text={chapter.title} animate={chapter.id === "hero" && phase < 3} />
                  </h1>
                  <p className="text-body-l mx-auto mt-3 max-w-xl text-ink-2">{chapter.text}</p>
                </motion.div>
              )}
            </AnimatePresence>
            {/* Where the reader is in the story: one mark per chapter. */}
            <div className="mt-6 flex justify-center gap-1.5" aria-hidden>
              {CHAPTERS.map((c, i) => (
                <motion.span key={c.id} layout transition={springs.rubber}
                  className={`h-1.5 rounded-full ${i === index ? "w-6 bg-ink" : "w-1.5 bg-line-strong"}`} />
              ))}
            </div>
          </div>
        </div>
      </div>

      <Section title="What it can and cannot do">
        CarLens sees what your video shows. A side you did not film is listed as not seen. A price needs at least three real
        listings; with fewer, the report says valuation unavailable instead of guessing. It is a demo, not a certified valuation.
      </Section>

      <footer className="mx-auto max-w-5xl border-t border-line px-4 py-10 sm:px-8">
        <p className="text-small text-ink-3">
          CarLens is a demo. Prices are estimates from public listings, not an offer or a certified valuation.
        </p>
      </footer>
    </div>
  );
}
