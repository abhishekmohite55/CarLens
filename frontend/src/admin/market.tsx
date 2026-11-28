// Stage M0 (docs/backend/07-us-market.md §13): one market switch for the whole admin app, in the header.
// "all" shows every market with an IN / US tag on each row; "in" / "us" shows only that market and no tags.
// Remembered in this browser. Every list asks the backend with ?market=in|us (nothing = all).
import { createContext, useContext, useState, type ReactNode } from "react";

export type MarketView = "all" | "in" | "us";
export type Market = "in" | "us";

const KEY = "carlens.admin.market";
const LABEL: Record<MarketView, string> = { all: "All", in: "India", us: "USA" };
// Market colours (owner, 26 Nov 2026): India saffron, US indigo; solid fills read in light and dark themes.
// Not blue (admin accent) or red (failed / error).
const FILL: Record<MarketView, string> = { all: "bg-ink text-page", in: "bg-amber-500 text-neutral-950", us: "bg-indigo-500 text-white" };

function saved(): MarketView {
  try {
    const value = localStorage.getItem(KEY);
    return value === "in" || value === "us" ? value : "all";
  } catch {
    return "all";
  }
}

const MarketContext = createContext<{ view: MarketView; setView: (v: MarketView) => void }>({ view: "all", setView: () => {} });

export function MarketProvider({ children }: { children: ReactNode }) {
  const [view, setViewState] = useState<MarketView>(saved);
  const setView = (v: MarketView) => {
    setViewState(v);
    try { localStorage.setItem(KEY, v); } catch { /* private mode: not remembered */ }
  };
  return <MarketContext.Provider value={{ view, setView }}>{children}</MarketContext.Provider>;
}

export function useMarket() {
  return useContext(MarketContext).view;
}

/** "market=us" for a query string, "" for all. */
export function marketParam(view: MarketView): string {
  return view === "all" ? "" : `market=${view}`;
}

/** path + market filter, keeping any query the path already has. */
export function withMarket(path: string, view: MarketView): string {
  const param = marketParam(view);
  if (!param) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${param}`;
}

/** Header control: All / India / USA. The selected market is filled with its colour (India saffron, US indigo). */
export function MarketSwitch() {
  const { view, setView } = useContext(MarketContext);
  return (
    <span role="group" aria-label="Market shown" className="inline-flex rounded-full bg-card p-1 shadow-card">
      {(["all", "in", "us"] as const).map((v) => (
        <button key={v} onClick={() => setView(v)} aria-pressed={view === v}
          className={`rounded-full px-3 py-1 text-xs font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${view === v ? FILL[v] : "text-ink-2 hover:text-ink"}`}>
          {LABEL[v]}
        </button>
      ))}
    </span>
  );
}

/** IN / US tag on a row, shown only while every market is shown. Nothing for rows that belong to no market. */
export function MarketTag({ market }: { market: string | null | undefined }) {
  const view = useMarket();
  if (view !== "all" || (market !== "in" && market !== "us")) return null;
  return (
    <span className={`ml-1.5 inline-block rounded px-1.5 py-px align-middle font-sans text-[10px] font-semibold tracking-wide ${FILL[market]}`}>
      {market === "us" ? "US" : "IN"}
    </span>
  );
}
