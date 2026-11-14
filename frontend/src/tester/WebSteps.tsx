// Stage F7: the web part of the run (docs/frontend/13-storyboard.md, Scenes 11–13): plan, search, read prices.
// Real queries, real sites and real snippets from the run's saved results. No Sent / Received (owner, 14 Nov).
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { springs } from "./motion";

// --- Shapes of the saved results (backend nodes plan / search / extract) ---
export type PlanQueries = {
  listing: string[]; new_price?: string[]; llm_called: boolean;
  parts: { part?: string; name?: string; queries: string[] }[];
  tyres: { item_id?: string; tier?: string; queries: string[] }[];
};
export type SearchResults = {
  queries: { query: string; kind?: string; for?: string; error: string | null; results: { title?: string; url: string; content?: string }[] }[];
  totals: { queries: number; results: number; unique_urls: number; failed: number };
};
export type Trimmed = { groups: { key: string; label: string; items: { id: string; domain: string; title: string; snippet: string }[] }[] };
export type Figures = {
  kept: { source: string; price_text: string[]; url?: string }[];
  rejected: { source: string; price_text: string[]; reason: string }[];
  outliers: { source: string; price_text: string[]; reason?: string }[];
};

/** Every query plan wrote, with what it is for. */
export function allQueries(q: PlanQueries): { text: string; tag: string }[] {
  return [
    ...q.listing.map((text) => ({ text, tag: "Used listings" })),
    ...(q.new_price ?? []).map((text) => ({ text, tag: "New price" })),
    ...q.parts.flatMap((p) => p.queries.map((text) => ({ text, tag: p.part ?? p.name ?? "Repair" }))),
    ...q.tyres.flatMap((t) => t.queries.map((text) => ({ text, tag: "Tyre" }))),
  ];
}

export const domainOf = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } };

/** Text typed in, letter by letter, then held (the search bar of Scene 11). */
export function Typing({ text }: { text: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0);
    const timer = setInterval(() => setShown((n) => (n >= text.length ? n : n + 1)), 45);
    return () => clearInterval(timer);
  }, [text]);
  return (
    <span className="whitespace-nowrap">
      {text.slice(0, shown)}
      <span className="ml-0.5 inline-block h-[1.1em] w-px translate-y-[0.15em] animate-pulse bg-current" aria-hidden />
    </span>
  );
}

const card = "rounded-panel bg-surface shadow-panel";

/** Plan done: the queries drop out of the search bar and stack below (Scene 11). */
export function QueryList({ queries, done }: { queries: { text: string; tag: string }[]; done?: number }) {
  return (
    <ol className="space-y-2">
      {queries.map((q, i) => (
        <motion.li key={q.text} initial={{ opacity: 0, y: -14 }} animate={{ opacity: 1, y: 0 }} transition={{ ...springs.settle, delay: i * 0.06 }}
          className={`${card} flex items-center justify-between gap-3 px-4 py-3`}>
          <span className="text-body min-w-0 truncate">{q.text}</span>
          <span className="text-small shrink-0 text-ink-3">{done !== undefined && i < done ? "done" : q.tag}</span>
        </motion.li>
      ))}
    </ol>
  );
}

/** Search done: under each query, its sites as small index cards (Scene 12). */
export function SearchRows({ search }: { search: SearchResults }) {
  return (
    <ol className="space-y-3">
      {search.queries.map((q, i) => (
        <motion.li key={`${q.query}-${i}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.05 }} className={`${card} px-4 py-3`}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-body min-w-0 truncate">{q.query}</p>
            <p className={`text-small shrink-0 ${q.error ? "text-danger-text" : "text-ink-3"}`}>
              {q.error ? "failed" : `${q.results.length} results`}
            </p>
          </div>
          {!q.error && q.results.length > 0 && (
            <div className="mt-2 flex gap-2 overflow-hidden">
              {q.results.slice(0, 4).map((r, j) => (
                <motion.a key={r.url} href={r.url} target="_blank" rel="noreferrer"
                  initial={{ opacity: 0, x: 24, rotate: 2 }} animate={{ opacity: 1, x: 0, rotate: 0 }}
                  transition={{ ...springs.settle, delay: i * 0.05 + j * 0.06 }}
                  className="w-44 shrink-0 rounded-input bg-top px-3 py-2 hover:bg-deep">
                  <span className="text-small block truncate text-ink-3">{domainOf(r.url)}</span>
                  <span className="text-small line-clamp-2 block text-ink">{r.title}</span>
                </motion.a>
              ))}
            </div>
          )}
        </motion.li>
      ))}
    </ol>
  );
}

const MONEY = /(₹|Rs\.?|INR)\s?[\d,.]+(\s?(lakh|lac|crore|k)\b)?|\b[\d.]+\s?(lakh|lac|crore)\b/gi;

/** Underlines anything that looks like a rupee amount (done in the browser, not by the AI). */
function Money({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(MONEY)) {
    parts.push(text.slice(last, m.index));
    parts.push(<span key={m.index} className="underline decoration-ink decoration-2 underline-offset-4">{m[0]}</span>);
    last = m.index! + m[0].length;
  }
  parts.push(text.slice(last));
  return <>{parts}</>;
}

/** While prices are read: the real snippets drift slowly upward, each headed by its site (Scene 13). */
export function Ticker({ trimmed, moving }: { trimmed: Trimmed; moving: boolean }) {
  const items = trimmed.groups.flatMap((g) => g.items);
  if (!items.length) return null;
  const list = (copy: number) => items.map((it) => (
    <div key={`${copy}-${it.id}`} className="border-b border-line px-4 py-3">
      <p className="text-small text-ink-3">{it.domain}</p>
      <p className="text-body text-ink-2"><Money text={it.snippet} /></p>
    </div>
  ));
  return (
    <div className={`${card} relative h-80 overflow-hidden`}>
      <motion.div animate={moving ? { y: ["0%", "-50%"] } : { y: "0%" }}
        transition={moving ? { duration: items.length * 4, ease: "linear", repeat: Infinity } : springs.settle}>
        {list(0)}{moving && list(1)}
      </motion.div>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-10 bg-gradient-to-b from-surface" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-surface" />
    </div>
  );
}

/** Prices read: kept ones green with a tick, dropped ones struck through with the reason. */
export function PriceList({ figures, trimmed }: { figures: Figures; trimmed?: Trimmed }) {
  const site = new Map(trimmed?.groups.flatMap((g) => g.items.map((it) => [it.id, it.domain] as const)) ?? []);
  type Row = { source: string; price_text: string[]; url?: string; kept: boolean; reason: string };
  const rows: Row[] = [
    ...figures.kept.map((f) => ({ ...f, kept: true, reason: "" })),
    ...[...figures.rejected, ...figures.outliers].map((f) => ({ ...f, kept: false, reason: f.reason ?? "dropped" })),
  ];
  return (
    <ul className={`${card} divide-y divide-line`}>
      <AnimatePresence>
        {rows.map((f, i) => (
          <motion.li key={`${f.source}-${i}`} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
            transition={{ ...springs.settle, delay: Math.min(i, 30) * 0.03 }} className="flex items-start justify-between gap-3 px-4 py-2.5">
            <span className="min-w-0">
              <span className={`text-body ${f.kept ? "text-ok-text" : "text-ink-3 line-through"}`}>
                {f.kept ? "✓ " : ""}{f.price_text.join(", ")}
              </span>
              {!f.kept && <span className="text-small ml-2 text-ink-3">{f.reason}</span>}
            </span>
            <span className="text-small shrink-0 text-ink-3">{site.get(f.source) ?? (f.url ? domainOf(f.url) : f.source)}</span>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
