import { useCallback } from "react";
import { api } from "../../shared/api";
import { MarketTag, useMarket, withMarket } from "../market";
import { td, th, useLoad, when } from "../ui";

// market (stage M0): the run / user / prompt the row is about; null = not market-linked (config, deploys)
type Entry = { id: number; at: string; admin: string | null; action: string; target: string | null; details: unknown; market: string | null };

export function Audit() {
  const market = useMarket();
  const load = useCallback(() => api<{ entries: Entry[] }>(withMarket("/api/admin/audit", market)), [market]);
  const { data, error } = useLoad(load);
  return (
    <div>
      <h1 className="mb-6 font-display text-xl sm:text-3xl font-light tracking-tight text-ink">Audit log</h1>
      {market !== "all" && <p className="-mt-4 mb-4 text-xs text-neutral-500">Rows not linked to a market (config, deploys) show under All only.</p>}
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
      {/* Mobile cards */}
      <div className="sm:hidden space-y-2">
        {data?.entries.map((e) => (
          <div key={e.id} className="rounded-2xl bg-card px-4 py-3 shadow-card">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm text-neutral-200">{e.action}<MarketTag market={e.market} /></span>
              <span className="shrink-0 text-xs text-neutral-500">{when(e.at)}</span>
            </div>
            {(e.admin || e.target) && (
              <div className="mt-0.5 text-xs text-neutral-500">
                {[e.admin, e.target].filter(Boolean).join(" · ")}
              </div>
            )}
            {e.details != null && JSON.stringify(e.details) !== "{}" && (
              <div className="mt-1 truncate font-mono text-[10px] text-neutral-600">
                {JSON.stringify(e.details)}
              </div>
            )}
          </div>
        ))}
        {data?.entries.length === 0 && <p className="mt-4 text-sm text-neutral-500">No admin changes yet.</p>}
      </div>
      {/* Desktop table */}
      <div className="hidden sm:block">
        <table className="w-full">
          <thead>
            <tr>{["When", "Admin", "Action", "Target", "Details"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {data?.entries.map((e) => (
              <tr key={e.id}>
                <td className={td}>{when(e.at)}</td>
                <td className={td}>{e.admin ?? "—"}</td>
                <td className={td}>{e.action}<MarketTag market={e.market} /></td>
                <td className={td}>{e.target}</td>
                <td className={`${td} font-mono text-xs text-neutral-400`}>{JSON.stringify(e.details)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.entries.length === 0 && <p className="mt-4 text-sm text-neutral-500">No admin changes yet.</p>}
      </div>
    </div>
  );
}
