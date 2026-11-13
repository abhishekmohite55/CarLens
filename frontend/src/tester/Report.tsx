// Stage F8: the price card and the report (docs/frontend/13-storyboard.md, Scenes 14–16; contents 02-design.md §5).
// Reads 09_report/report.json, written by the backend's report node (Python only, no AI).
import { motion } from "motion/react";
import type { ReactNode } from "react";
import { springs } from "./motion";
import { RollingNumber } from "./RollingNumber";
import { domainOf } from "./WebSteps";

type Link = { id?: string; url?: string; title?: string } | string;
type Where = { time?: string | null; side?: string | null; frame?: string | null };
export type Report = {
  vehicle: { make?: string; model?: string; variant?: string; year?: number; fuel?: string; plate?: string; city?: string;
    state?: string; odometer_km?: number; km_from?: string; plate_from?: string; changed?: string[] };
  price: { status: "ok"; low: number; high: number; new_price: { value: number; sources: Link[] };
    listings_used: { year: number; price: number; source: Link }[]; how: string[] } | { status: "unavailable"; reason: string };
  condition_summary: string[];
  damage: ({ item_id: string; part?: string; issue?: string; severity?: string; action?: string; description?: string } & Where)[];
  tyres: ({ position?: string; tyre_score?: number | null; tread?: string | null; from: string; tier?: string; description?: string } & Where)[];
  repairs: { items: { for: string; cost: number; up_to?: number; note?: string; sources: Link[] }[]; total: number; cost_unavailable: string[] };
  coverage: { sides_seen: string[]; sides_not_seen: string[]; tyres_not_seen: string[]; odometer?: string; plate?: string;
    skipped: string[]; not_confirmed: { item_id?: string; label?: string; reason?: string }[] };
};

export const inr = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`;
const words = (s?: string | null) => (s ?? "").replace(/_/g, " ");
export const carName = (v: Report["vehicle"]) => [v.make, v.model, v.variant, v.year].filter(Boolean).join(" ");

function SourceLink({ link }: { link: Link }) {
  const url = typeof link === "string" ? undefined : link.url;
  if (!url) return <span className="text-small text-ink-3">{typeof link === "string" ? link : link.id}</span>;
  return <a href={url} target="_blank" rel="noreferrer" className="text-small text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink">{domainOf(url)}</a>;
}

/** The price card: the Lens at its largest. Digits roll in. No working shown (owner, 14 Nov). */
export function PriceCard({ report }: { report: Report }) {
  const p = report.price;
  return (
    <div className="space-y-4 p-6 sm:p-8">
      <p className="text-small opacity-75">{carName(report.vehicle)}{report.vehicle.fuel ? `, ${report.vehicle.fuel}` : ""}</p>
      {p.status === "ok" ? (
        <>
          <p className="text-title"><RollingNumber text={`${inr(p.low)} to ${inr(p.high)}`} /></p>
          <p className="text-body opacity-80">
            Fair value after repairs, from {p.listings_used.length} listings and {p.new_price.sources.length} new-price sources.
          </p>
        </>
      ) : (
        <>
          <p className="text-title">Valuation unavailable</p>
          <p className="text-body opacity-85">{p.reason}</p>
          <p className="text-small opacity-70">Everything else in the report is complete.</p>
        </>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <motion.section initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }}
      transition={springs.settle} className="mt-16">
      <h2 className="text-heading">{title}</h2>
      <div className="mt-5">{children}</div>
    </motion.section>
  );
}

const card = "rounded-panel bg-surface shadow-panel";

export function ReportBody({ report, runId }: { report: Report; runId: string }) {
  const v = report.vehicle;
  const file = (path: string) => `/api/runs/${runId}/files/${path}`;
  const facts: [string, ReactNode][] = [
    ["Car", carName(v) || "—"], ["Fuel", v.fuel || "—"],
    ["Plate", v.plate ? `${v.plate}${v.plate_from ? `, ${words(v.plate_from)}` : ""}` : "not read"],
    ["City", v.city ? `${v.city}${v.state ? `, ${v.state}` : ""}` : "—"],
    ["Odometer", v.odometer_km != null ? `${v.odometer_km.toLocaleString("en-IN")} km${v.km_from ? `, ${words(v.km_from)}` : ""}` : "not read"],
  ];
  const c = report.coverage;
  const notChecked = [
    ...c.sides_not_seen.map((s) => `${words(s)} side was not in the video.`),
    ...c.tyres_not_seen.map((t) => `${words(t)} tyre was not seen.`),
    ...c.not_confirmed.map((n) => `${n.label ?? n.item_id}: spotted but not confirmed${n.reason ? ` (${n.reason})` : ""}.`),
    ...c.skipped.map((s) => `${words(s)} was skipped.`),
  ];
  const p = report.price;

  return (
    <div>
      <Section title="Your car">
        <dl className={`${card} grid gap-x-8 gap-y-3 px-5 py-4 sm:grid-cols-2`}>
          {facts.map(([k, val]) => (
            <div key={k} className="flex justify-between gap-4 sm:block">
              <dt className="text-small text-ink-3">{k}</dt>
              <dd className="text-body">{val}</dd>
            </div>
          ))}
        </dl>
        {!!v.changed?.length && <p className="text-small mt-3 text-ink-3">Edited by you: {v.changed.map(words).join(", ")}.</p>}
      </Section>

      <Section title="Condition">
        <div className="text-body-l max-w-2xl space-y-2 text-ink-2">{report.condition_summary.map((s, i) => <p key={i}>{s}</p>)}</div>
      </Section>

      <Section title="Damage found">
        {report.damage.length === 0 ? <p className="text-body text-ink-3">No damage was confirmed in the video.</p> : (
          <div className="grid gap-4 sm:grid-cols-2">
            {report.damage.map((d) => (
              <article key={d.item_id} className={`${card} overflow-hidden`}>
                {d.frame && <img src={file(d.frame)} alt={`${words(d.part)}, ${words(d.issue)}`} loading="lazy" className="aspect-video w-full object-cover" />}
                <div className="space-y-1 px-5 py-4">
                  <p className="text-label">{[words(d.part), words(d.issue), d.severity, d.action !== "none" ? d.action : ""].filter(Boolean).join(", ")}</p>
                  {d.description && <p className="text-body text-ink-2">{d.description}</p>}
                  {d.time && <p className="text-small text-ink-3">At {d.time} in your video</p>}
                </div>
              </article>
            ))}
          </div>
        )}
      </Section>

      <Section title="Tyres">
        {report.tyres.length === 0 ? <p className="text-body text-ink-3">Tyres were not assessed.</p> : (
          // Laid out like the car: front pair above the rear pair.
          <div className="grid grid-cols-2 gap-4">
            {[...report.tyres].sort((a, b) => (a.position ?? "").localeCompare(b.position ?? "")).map((t, i) => (
              <article key={`${t.position}-${i}`} className={`${card} overflow-hidden`}>
                {t.frame && <img src={file(t.frame)} alt={`${words(t.position)} tyre`} loading="lazy" className="aspect-[4/3] w-full object-cover" />}
                <div className="space-y-1 px-4 py-3">
                  <p className="text-label">{words(t.position) || "Tyre"}{t.from === "photo" ? " (your photo)" : ""}</p>
                  <p className="text-body tabular-nums">{t.tyre_score != null ? `${t.tyre_score} of 10` : "Score unclear"}{t.tread ? `, ${t.tread}` : ""}</p>
                  {t.tier && <p className="text-small text-ink-3">{words(t.tier)}</p>}
                </div>
              </article>
            ))}
          </div>
        )}
      </Section>

      <Section title="Repair costs">
        {report.repairs.items.length === 0 && report.repairs.cost_unavailable.length === 0 ? (
          <p className="text-body text-ink-3">Nothing to repair was priced.</p>
        ) : (
          <div className={`${card} divide-y divide-line`}>
            {report.repairs.items.map((r) => (
              <div key={r.for} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3">
                <span className="text-body">{words(r.for)}</span>
                <span className="text-body tabular-nums">{inr(r.cost)}
                  {r.up_to && r.up_to > r.cost && <span className="text-small ml-2 text-ink-3">could be up to {inr(r.up_to)}</span>}
                </span>
                <span className="flex w-full flex-wrap gap-3">
                  {r.note && <span className="text-small text-ink-3">{r.note}</span>}
                  {r.sources.map((s, i) => <SourceLink key={i} link={s} />)}
                </span>
              </div>
            ))}
            {report.repairs.cost_unavailable.map((u) => (
              <div key={u} className="flex justify-between gap-4 px-5 py-3">
                <span className="text-body">{u}</span><span className="text-small text-ink-3">Cost unavailable, no price found</span>
              </div>
            ))}
            <div className="flex justify-between gap-4 px-5 py-3">
              <span className="text-label">Total taken off the price</span>
              <span className="text-label tabular-nums">{inr(report.repairs.total)}</span>
            </div>
          </div>
        )}
        <p className="text-small mt-3 text-ink-3">Typical cost is the middle of the prices found. Follow the links to check or buy the part.</p>
      </Section>

      {p.status === "ok" && (
        <Section title="Where the prices came from">
          <div className={`${card} max-w-2xl divide-y divide-line`}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 py-3">
              <span className="text-body"><span className="text-label mr-2">New car today</span><span className="tabular-nums">{inr(p.new_price.value)}</span></span>
              <span className="flex flex-wrap gap-3">{p.new_price.sources.map((s, i) => <SourceLink key={i} link={s} />)}</span>
            </div>
            <p className="text-small bg-deep/50 px-5 py-2 text-ink-3">Used listings compared ({p.listings_used.length})</p>
            {p.listings_used.map((l, i) => (
              <div key={i} className="flex items-baseline justify-between gap-4 px-5 py-2.5">
                <span className="text-body tabular-nums">{l.year}, {inr(l.price)}</span><SourceLink link={l.source} />
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Not checked">
        {notChecked.length === 0 ? <p className="text-body text-ink-3">Every side, tyre and reading was covered.</p> : (
          <ul className="text-body max-w-2xl list-disc space-y-1.5 pl-5 text-ink-2">
            {notChecked.map((n, i) => <li key={i} className="first-letter:uppercase">{n}</li>)}
          </ul>
        )}
      </Section>
    </div>
  );
}
