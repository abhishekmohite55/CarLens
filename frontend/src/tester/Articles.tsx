// F10 articles (owner, 14 Nov): "How CarLens works" kept short, and "Questions". No method details, no providers:
// testers are not given everything. Open to anyone, signed in or not.
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Footer } from "./Footer";
import { springs } from "./motion";
import { useSession } from "./session";
import { ThemeToggle } from "./theme";

function Page({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  const { me } = useSession();
  return (
    <div className="min-h-svh bg-canvas text-ink">
      <header className="flex items-center justify-between gap-3 px-4 pt-4 sm:px-8 sm:pt-6">
        <Link to={me ? "/home" : "/"} className="text-heading">CarLens</Link>
        <ThemeToggle />
      </header>
      <main className="mx-auto max-w-2xl px-4 pt-16 sm:px-8">
        <h1 className="text-title">{title}</h1>
        <p className="text-body-l mt-4 text-ink-2">{intro}</p>
        <div className="mt-12">{children}</div>
      </main>
      <Footer />
    </div>
  );
}

const STEPS = [
  ["You film the car", "Walk around it once, slowly. Up to a few minutes of video."],
  ["The moments are found", "AI marks where the plate, badge, odometer, tyres and any damage appear."],
  ["The sharpest frames are kept", "One clear picture of each moment."],
  ["The plate is read", "So the car's city can be filled in for you."],
  ["The findings are checked", "Real damage is kept; reflections and dirt are set aside."],
  ["You confirm the details", "Fix anything the AI got wrong, and add tyre photos if you like."],
  ["The web is searched", "For today's prices of your car and of any repairs."],
  ["Prices are read and checked", "Only prices that really appear on their page are used."],
  ["The price range is worked out", "Repairs are taken off, and the report shows where every figure came from."],
];

export function HowItWorks() {
  return (
    <Page title="How CarLens works" intro="From a walkaround video to a price range in rupees, in nine steps. A run takes about 8 to 12 minutes; one step needs you.">
      <ol className="space-y-6 border-l border-line pl-6">
        {STEPS.map(([title, text], i) => (
          <motion.li key={title} initial={{ opacity: 0, x: -10 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }}
            transition={{ ...springs.settle, delay: i * 0.04 }}>
            <p className="text-label text-ink-3 tabular-nums">{i + 1}</p>
            <p className="text-heading mt-1">{title}</p>
            <p className="text-body mt-1 text-ink-2">{text}</p>
          </motion.li>
        ))}
      </ol>
    </Page>
  );
}

const QUESTIONS = [
  ["Is this a real valuation?", "No. It is an estimate from public listings, made for a demo. It is not an offer."],
  ["Why is my price unavailable?", "Not enough listings of your car were found to work out a range. The report says what was missing."],
  ["Why did the AI get the year wrong?", "The year is hard to see on a car. Change it when you confirm the details; the price uses your value."],
  ["What does \"the next one is answering\" mean?", "The first AI was busy or slow, so another one answered. This is normal and costs you nothing."],
  ["Can I leave during a run?", "Yes. The run keeps going. Open it again from Home; if it needs you, Home says so."],
  ["What are runs left?", "Each new video uses one run. Resuming a run that stopped is free. Ask the owner if you need more."],
  ["Which videos work best?", "Daylight, one slow walk around the car, and a second of the plate, each tyre and the odometer in view."],
];

export function Questions() {
  return (
    <Page title="Questions" intro="Short answers to what testers ask most.">
      <div className="divide-y divide-line">
        {QUESTIONS.map(([q, a]) => (
          <details key={q} className="group py-5">
            <summary className="text-heading flex cursor-pointer list-none items-center justify-between gap-4">
              {q}<span className="text-ink-3 transition-transform group-open:rotate-45" aria-hidden>+</span>
            </summary>
            <p className="text-body mt-3 text-ink-2">{a}</p>
          </details>
        ))}
      </div>
    </Page>
  );
}
