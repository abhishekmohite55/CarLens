// Dashboard (docs/platform/06-admin.md §6.6). Numbers from GET /api/admin/dashboard.
// Design (owner, 12 Nov, from two reference shots): soft rounded cards, big quiet numbers, hatched marks, one highlight card;
// the pipeline drawn as a funnel. Light and dark theme (src/admin/theme.tsx). Colours: dataviz reference palette,
// light / dark steps; green and red only mean finished / failed.
import { useCallback, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../../shared/api";
import { useTheme, type Theme } from "../theme";
import { useLoad, when } from "../ui";

type Dash = {
  days: number;
  runs_per_day: { day: string; status: string; n: number }[];
  steps: { node: string; done: number; failed: number; avg_sec: number | null; max_sec: number | null }[];
  last_errors: { node: string; run_id: string; error: string | null; at: string | null }[];
  models: { node: string; model: string | null; answers: number; after_fallback: number }[];
  tavily: { queries_this_month: number; free_credits: number; note: string };
  access: { pending: number; approved: number; locked: number };
  tokens: { email: string; tokens_left: number; runs: number }[];
  prices: { status: string; n: number }[];
  in_progress: { run_id: string; status: string; file: string | null; user: string | null; since: string }[];
  langfuse_url: string | null;
};

const PIPELINE = ["locate", "frames", "verify", "photos", "plan", "search", "extract", "pricing", "report"];
const STEP_NAMES: Record<string, string> = {
  locate: "Locate", frames: "Frames", verify: "Verify", photos: "Photos", plan: "Plan",
  search: "Search", extract: "Extract", pricing: "Pricing", report: "Report",
};
const AI_STEPS = ["verify", "photos", "plan", "extract"];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Per-theme colours. Status: green finished, red failed; the rest neutral or series hues.
const PALETTE: Record<Theme, { series: string[]; other: string; status: Record<string, string>; grid: string; axis: string }> = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"],
    other: "#a4a9b2",
    status: { complete: "#0ca30c", partial: "#a4a9b2", failed: "#d03b3b", awaiting_confirm: "#6250d6", running: "#2a78d6", uploaded: "#7fa6d9" },
    grid: "#eef0f3", axis: "#868c97",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"],
    other: "#5a606b",
    status: { complete: "#0ca30c", partial: "#5f6570", failed: "#d03b3b", awaiting_confirm: "#9085e9", running: "#3987e5", uploaded: "#5b7fb0" },
    grid: "#272b31", axis: "#737a85",
  },
};
const STATUS_ORDER = [
  ["complete", "Finished"], ["partial", "Stopped"], ["failed", "Failed"],
  ["awaiting_confirm", "Awaiting confirmation"], ["running", "Running"], ["uploaded", "Uploaded"],
] as const;

/** Fine diagonal lines in one colour over a pale tint of it. */
const hatch = (color: string): CSSProperties => ({
  backgroundImage: `repeating-linear-gradient(135deg, color-mix(in srgb, ${color} 80%, transparent) 0 1.5px, color-mix(in srgb, ${color} 22%, transparent) 1.5px 5px)`,
});

function seconds(s: number | null): string {
  if (s === null) return "—";
  return s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s}s`;
}

function shortWhen(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
}

function shortModel(model: string | null): string {
  if (!model) return "none answered";
  return model.split("/").pop()!.replace(/:free$/, "");
}

function Card({ title, aside, className = "", children }: { title: string; aside?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`rounded-[24px] bg-card p-5 shadow-card ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-display text-[17px] font-medium tracking-tight text-ink">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Pill({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "solid" }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs ${tone === "solid" ? "bg-ink text-page" : "bg-inset text-ink-2"}`}>
      {children}
    </span>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-2xl bg-inset px-4 py-6 text-center text-sm text-ink-3">{children}</p>;
}

/** The nine steps as a funnel: attempts that reached each step, failed share as a red cap, side faces show the drop. */
function PipelineFunnel({ steps }: { steps: Dash["steps"] }) {
  const byNode = Object.fromEntries(steps.map((s) => [s.node, s]));
  const cols = PIPELINE.map((node) => {
    const s = byNode[node];
    return { node, done: s?.done ?? 0, failed: s?.failed ?? 0, runs: s ? s.done + s.failed : 0, avg: s?.avg_sec ?? null, max: s?.max_sec ?? null };
  });
  const top = Math.max(1, ...cols.map((c) => c.runs));
  // Open on the step that loses the most attempts against the one before it.
  const biggestDrop = cols.reduce((best, c, i) => (i && cols[i - 1].runs - c.runs > (best ? cols[best - 1].runs - cols[best].runs : 0) ? i : best), 0);
  const [active, setActive] = useState<number | null>(null);
  const shown = active ?? biggestDrop;
  const pct = (n: number) => `${(n / top) * 82}%`;

  if (cols.every((c) => c.runs === 0)) return <Empty>No step ran in this period. Each upload shows here as it moves through the steps.</Empty>;
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <ol className="grid min-w-[680px] grid-cols-9" onMouseLeave={() => setActive(null)} aria-label="Pipeline steps">
        {cols.map((c, i) => {
          const isOn = i === shown;
          const prev = i ? cols[i - 1].runs : null;
          const change = prev ? Math.round(((c.runs - prev) / prev) * 100) : null;
          const next = cols[i + 1];
          return (
            <li key={c.node} tabIndex={0} onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)}
              className={`relative rounded-2xl outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent ${isOn ? "bg-gradient-to-b from-inset to-transparent" : ""}`}>
              <div className="px-2 pt-2">
                <div className={`text-xs ${isOn ? "text-ink" : "text-ink-3"}`}>{STEP_NAMES[c.node]}</div>
                <div className={`font-display text-2xl font-light tabular-nums tracking-tight ${isOn ? "text-ink" : "text-ink-3"}`}>{c.runs}</div>
              </div>
              <div className="relative mt-2 h-44">
                {next && (
                  <div aria-hidden="true" className="absolute bottom-0 left-[70%] h-full w-[30%] bg-accent/15"
                    style={{ clipPath: `polygon(0 ${100 - (c.runs / top) * 82}%, 100% ${100 - (next.runs / top) * 82}%, 100% 100%, 0 100%)` }} />
                )}
                <div className="absolute bottom-0 left-0 flex w-[70%] flex-col overflow-hidden rounded-t-[6px] motion-safe:transition-[height] motion-safe:duration-500"
                  style={{ height: pct(c.runs) }}>
                  {c.failed > 0 && <div className="shrink-0 bg-bad" style={{ height: `${(c.failed / c.runs) * 100}%`, minHeight: 3 }} title={`${c.failed} failed`} />}
                  <div className="flex-1" style={isOn ? { background: "var(--t-accent)" } : hatch("var(--t-accent)")} />
                </div>
                <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-card/70 to-transparent" />
              </div>
              {isOn && (
                <div role="status" className="absolute left-1/2 top-[4.75rem] z-10 -translate-x-1/2 whitespace-nowrap rounded-full bg-card px-3 py-1.5 text-xs text-ink-2 shadow-card ring-1 ring-line">
                  <b className="font-semibold text-ink">{c.runs}</b> attempts
                  {c.failed > 0 && <> <span className="text-line">|</span> <span className="text-bad">{c.failed} failed</span></>}
                  {c.avg !== null && <> <span className="text-line">|</span> typical {seconds(c.avg)}</>}
                  {c.max !== null && <> <span className="text-line">|</span> slowest {seconds(c.max)}</>}
                  {change !== null && <> <span className="text-line">|</span> {change > 0 ? "+" : ""}{change}% from {STEP_NAMES[cols[i - 1].node]}</>}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function RunsTotal({ data, colors }: { data: Dash["runs_per_day"]; colors: Record<string, string> }) {
  const counts = Object.fromEntries(STATUS_ORDER.map(([k]) => [k, data.filter((r) => r.status === k).reduce((n, r) => n + r.n, 0)]));
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="flex items-end gap-3">
        <span className="font-display text-6xl font-light tabular-nums tracking-tighter text-ink">{total}</span>
        {total > 0 && <span className="mb-2"><Pill>{Math.round((counts.complete / total) * 100)}% finished</Pill></span>}
      </div>
      <ul className="mt-6 space-y-4">
        {STATUS_ORDER.filter(([k]) => counts[k] > 0).map(([k, label]) => (
          <li key={k}>
            <div className="mb-1.5 flex justify-between text-sm">
              <span className="text-ink-2">{label}</span>
              <span className="font-medium tabular-nums text-ink">{counts[k]}</span>
            </div>
            <div className="h-2 rounded-full bg-inset">
              <div className="h-2 rounded-full" style={{ width: `${(counts[k] / total) * 100}%`, ...hatch(colors[k]) }} />
            </div>
          </li>
        ))}
      </ul>
      {total === 0 && <Empty>No runs yet in this period.</Empty>}
    </>
  );
}

function RunsPerDay({ data, theme }: { data: Dash["runs_per_day"]; theme: Theme }) {
  const p = PALETTE[theme];
  const present = STATUS_ORDER.filter(([k]) => data.some((r) => r.status === k));
  const days = Object.values(data.reduce<Record<string, Record<string, number | string>>>((acc, r) => {
    (acc[r.day] ??= { day: r.day })[r.status] = r.n;
    return acc;
  }, {}));
  if (days.length === 0) return <Empty>Uploads show up here by day.</Empty>;
  return (
    <>
      <ResponsiveContainer width="100%" height={236}>
        <BarChart data={days} margin={{ top: 4, right: 0, left: -28, bottom: 0 }} barCategoryGap="12%">
          <CartesianGrid stroke={p.grid} vertical={false} />
          <XAxis dataKey="day" stroke={p.axis} fontSize={11} tickLine={false} axisLine={false}
            tickFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" })} />
          <YAxis allowDecimals={false} stroke={p.axis} fontSize={11} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ fill: "var(--t-inset)", radius: 8 } as object}
            contentStyle={{ background: "var(--t-card)", border: "1px solid var(--t-line)", borderRadius: 14, color: "var(--t-ink)", fontSize: 12 }}
            labelFormatter={(d) => new Date(String(d)).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} />
          {present.map(([k, label], i) => (
            <Bar key={k} dataKey={k} name={label} stackId="runs" fill={p.status[k]} stroke="var(--t-card)" strokeWidth={1.5}
              radius={i === present.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={22} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
        {present.map(([k, label]) => (
          <li key={k} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: p.status[k] }} />{label}</li>
        ))}
      </ul>
    </>
  );
}

/** Runs per weekday as dot columns; the busiest day is the solid column. */
function Weekdays({ data, days }: { data: Dash["runs_per_day"]; days: number }) {
  const per = [0, 0, 0, 0, 0, 0, 0];
  data.forEach((r) => { per[(new Date(r.day).getDay() + 6) % 7] += r.n; });
  const total = per.reduce((a, b) => a + b, 0);
  const most = Math.max(...per);
  const busiest = per.indexOf(most);
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        <div className="font-display text-4xl font-light tabular-nums tracking-tight text-ink">{(total / days).toFixed(1)}</div>
        <div className="text-xs text-ink-3">runs a day on average</div>
      </div>
      <div className="relative flex items-end gap-1.5" aria-label={`Runs per weekday: ${WEEKDAYS.map((d, i) => `${d} ${per[i]}`).join(", ")}`}>
        {total > 0 && <span className="absolute -top-7 whitespace-nowrap" style={{ left: `${busiest * 18 - 10}px` }}><Pill>Busiest: <b className="font-semibold text-ink">{WEEKDAYS[busiest]}</b></Pill></span>}
        {per.map((n, i) => {
          const dots = n ? Math.max(1, Math.round((n / most) * 5)) : 0;
          return (
            <div key={i} className="flex w-3 flex-col items-center gap-1" title={`${WEEKDAYS[i]}: ${n} runs`}>
              <div className="flex flex-col-reverse gap-1">
                {Array.from({ length: 5 }, (_, j) => (
                  <span key={j} className={`h-2.5 w-2.5 rounded-full ${j < dots ? (i === busiest ? "bg-accent" : "bg-accent/40") : "bg-inset"}`} />
                ))}
              </div>
              <span className="mt-0.5 text-[10px] text-ink-3">{WEEKDAYS[i][0]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NeedsYou({ d }: { d: Dash }) {
  const rows = [
    { n: d.access.pending, text: d.access.pending === 1 ? "access request" : "access requests" },
    { n: d.access.locked, text: d.access.locked === 1 ? "locked account" : "locked accounts" },
  ];
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <Link key={r.text} to="/users"
          className="flex items-center justify-between rounded-2xl bg-inset px-4 py-2.5 transition-colors hover:bg-line focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <span className="text-sm text-ink-2">{r.text}</span>
          <span className={`font-display text-xl tabular-nums ${r.n ? "text-ink" : "text-ink-3"}`}>{r.n}</span>
        </Link>
      ))}
      <p className="px-1 pt-1 text-xs text-ink-3">
        {d.in_progress.length === 0 ? "Nothing is running." : `${d.in_progress.length} run${d.in_progress.length === 1 ? "" : "s"} in progress: ${d.in_progress.slice(0, 2).map((r) => r.user ?? r.file ?? r.run_id).join(", ")}${d.in_progress.length > 2 ? "…" : ""}`}
      </p>
    </div>
  );
}

/** The one thing worth a look, picked from the numbers in this order. */
function Highlight({ d }: { d: Dash }) {
  const worst = d.steps
    .map((s) => ({ ...s, runs: s.done + s.failed }))
    .filter((s) => s.runs >= 3 && s.failed / s.runs >= 0.1)
    .sort((a, b) => b.failed / b.runs - a.failed / a.runs)[0];
  const tavily = Math.round((d.tavily.queries_this_month / d.tavily.free_credits) * 100);
  const priced = d.prices.reduce((s, p) => s + p.n, 0);
  const found = priced ? Math.round(((priced - (d.prices.find((p) => p.status === "unavailable")?.n ?? 0)) / priced) * 100) : null;
  const runs = d.runs_per_day.reduce((n, r) => n + r.n, 0);

  const pick = d.access.pending > 0
    ? { big: String(d.access.pending), line: d.access.pending === 1 ? "person is waiting for access." : "people are waiting for access.", small: "Approve or reject them so they can start their runs.", link: { to: "/users", text: "Review requests" } }
    : worst
      ? { big: `${Math.round((worst.failed / worst.runs) * 100)}%`, line: `of ${STEP_NAMES[worst.node] ?? worst.node} attempts failed.`, small: d.last_errors.find((e) => e.node === worst.node)?.error ?? "See the runs for the error.", link: { to: "/runs", text: "Open runs" } }
      : tavily >= 80
        ? { big: `${tavily}%`, line: "of this month's free Tavily searches are used.", small: d.tavily.note, link: null }
        : found !== null
          ? { big: `${found}%`, line: "of priced runs found a price.", small: `From ${priced} runs that reached pricing in the last ${d.days} days.`, link: null }
          : { big: String(runs), line: `runs in the last ${d.days} days.`, small: "Nothing needs you right now.", link: null };

  return (
    <section className="relative flex h-full min-h-[260px] flex-col justify-end overflow-hidden rounded-[24px] p-6 text-white shadow-card"
      style={{ background: "radial-gradient(120% 90% at 100% 0%, #eb6834cc 0%, transparent 55%), radial-gradient(90% 80% at 0% 100%, #2a78d6 0%, transparent 70%), radial-gradient(70% 70% at 100% 100%, #e3b341aa 0%, transparent 60%), #1d2a4d" }}>
      <span className="absolute left-5 top-5 rounded-full bg-white/15 px-3 py-1 text-xs backdrop-blur">Worth a look</span>
      <div className="font-display text-6xl font-light tabular-nums tracking-tighter">{pick.big}</div>
      <p className="mt-1 max-w-[30ch] text-lg leading-snug">{pick.line}</p>
      <p className="mt-2 line-clamp-2 max-w-[42ch] text-sm text-white/75">{pick.small}</p>
      {pick.link && (
        <Link to={pick.link.to} className="mt-4 self-start rounded-full bg-white px-4 py-1.5 text-sm font-medium text-[#16181c] transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70">
          {pick.link.text}
        </Link>
      )}
    </section>
  );
}

/** Which model answered each AI step: hatched segments, a model keeps its colour on every row. */
function ModelAnswers({ models, theme }: { models: Dash["models"]; theme: Theme }) {
  const p = PALETTE[theme];
  const ranked = useMemo(() => {
    const totals = new Map<string, number>();
    models.forEach((m) => totals.set(shortModel(m.model), (totals.get(shortModel(m.model)) ?? 0) + m.answers));
    return [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name]) => name);
  }, [models]);
  const color = (name: string) => (ranked.indexOf(name) < p.series.length ? p.series[ranked.indexOf(name)] : p.other);
  const rows = AI_STEPS.map((node) => ({ node, parts: models.filter((m) => m.node === node) })).filter((r) => r.parts.length);
  if (rows.length === 0) return <Empty>No AI answers in this period.</Empty>;
  return (
    <div className="space-y-5">
      {rows.map(({ node, parts }) => {
        const total = parts.reduce((n, x) => n + x.answers, 0);
        const fallbacks = parts.reduce((n, x) => n + x.after_fallback, 0);
        return (
          <div key={node}>
            <div className="mb-2 flex items-baseline justify-between text-sm">
              <span className="text-ink">{STEP_NAMES[node]}</span>
              <span className="tabular-nums text-ink-3">{total} answers{fallbacks ? `, ${fallbacks} after a fallback` : ""}</span>
            </div>
            <div className="flex h-2.5 gap-1">
              {parts.map((x) => (
                <div key={x.model ?? "none"} className="rounded-full" title={`${shortModel(x.model)}: ${x.answers}`}
                  style={{ width: `${(x.answers / total) * 100}%`, ...hatch(color(shortModel(x.model))) }} />
              ))}
            </div>
          </div>
        );
      })}
      <ul className="flex flex-wrap gap-2 pt-1">
        {ranked.slice(0, p.series.length).map((name) => (
          <li key={name}><Pill><span className="h-2 w-2 rounded-full" style={{ background: color(name) }} />{name}</Pill></li>
        ))}
        {ranked.length > p.series.length && <li><Pill><span className="h-2 w-2 rounded-full" style={{ background: p.other }} />other</Pill></li>}
      </ul>
    </div>
  );
}

function Usage({ d }: { d: Dash }) {
  const share = Math.min(100, (d.tavily.queries_this_month / d.tavily.free_credits) * 100);
  const priced = d.prices.reduce((s, p) => s + p.n, 0);
  const unavailable = d.prices.find((p) => p.status === "unavailable")?.n ?? 0;
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline gap-2">
          <span className="font-display text-4xl font-light tabular-nums tracking-tight text-ink">{d.tavily.queries_this_month}</span>
          <span className="text-sm text-ink-3">of {d.tavily.free_credits.toLocaleString()} free</span>
        </div>
        <div className="mt-1 text-xs text-ink-3" title={d.tavily.note}>Tavily searches this month (approximate)</div>
        <div className="mt-3 h-2 rounded-full bg-inset">
          <div className="h-2 rounded-full" style={{ width: `${Math.max(share, d.tavily.queries_this_month ? 2 : 0)}%`, ...hatch(share > 80 ? "#fab219" : "var(--t-accent)") }} />
        </div>
      </div>
      <div className="rounded-2xl bg-inset px-4 py-3">
        <div className="text-xs text-ink-3">No price found</div>
        <div className="mt-0.5 flex items-baseline gap-2">
          <span className="font-display text-2xl font-light tabular-nums text-ink">{priced ? `${Math.round((unavailable / priced) * 100)}%` : "—"}</span>
          <span className="text-xs text-ink-3">{priced ? `${unavailable} of ${priced} priced runs` : "no priced runs yet"}</span>
        </div>
      </div>
    </div>
  );
}

function Testers({ tokens }: { tokens: Dash["tokens"] }) {
  if (tokens.length === 0) return <Empty>No approved testers yet.</Empty>;
  return (
    <ul className="space-y-1">
      {tokens.slice(0, 6).map((t) => (
        <li key={t.email} className="flex items-center gap-3 rounded-2xl px-1 py-1.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-inset text-sm font-medium uppercase text-ink-2" aria-hidden="true">{t.email[0]}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-ink" title={t.email}>{t.email}</span>
            <span className="text-xs text-ink-3">{t.runs} run{t.runs === 1 ? "" : "s"}</span>
          </span>
          <Pill>{t.tokens_left} left</Pill>
        </li>
      ))}
      {tokens.length > 6 && <li className="px-1 pt-1 text-xs text-ink-3"><Link to="/users" className="underline-offset-4 hover:underline">{tokens.length - 6} more in Users</Link></li>}
    </ul>
  );
}

export function Dashboard() {
  const { theme } = useTheme();
  const [days, setDays] = useState(30);
  const load = useCallback(() => api<Dash>(`/api/admin/dashboard?days=${days}`), [days]);
  const { data: d, error } = useLoad(load);

  return (
    <div className="mx-auto max-w-[1320px]">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <h1 className="font-display text-5xl font-light tracking-tighter text-ink">Dashboard</h1>
        <div className="flex items-center gap-2">
          {d?.langfuse_url && (
            <a className="rounded-full bg-card px-4 py-2 text-sm text-ink-2 shadow-card transition-colors hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              href={d.langfuse_url} target="_blank" rel="noreferrer">AI cost in Langfuse</a>
          )}
          <div role="radiogroup" aria-label="Period" className="flex gap-0.5 rounded-full bg-card p-1 shadow-card">
            {[7, 30, 90].map((n) => (
              <button key={n} role="radio" aria-checked={days === n} onClick={() => setDays(n)}
                className={`rounded-full px-4 py-1.5 text-sm tabular-nums transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${days === n ? "bg-ink text-page" : "text-ink-2 hover:text-ink"}`}>
                {n} days
              </button>
            ))}
          </div>
        </div>
      </header>

      {!d ? <p className="text-sm text-ink-3">{error || "Loading…"}</p> : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Card title="Pipeline" className="lg:col-span-8" aside={<span className="text-xs text-ink-3">attempts per step, last {d.days} days</span>}>
            <PipelineFunnel steps={d.steps} />
          </Card>
          <Card title="Runs" className="lg:col-span-4">
            <RunsTotal data={d.runs_per_day} colors={PALETTE[theme].status} />
          </Card>

          <Card title="Runs per day" className="lg:col-span-4">
            <RunsPerDay data={d.runs_per_day} theme={theme} />
          </Card>
          <div className="grid gap-4 lg:col-span-4">
            <Card title="By weekday"><Weekdays data={d.runs_per_day} days={d.days} /></Card>
            <Card title="Needs you"><NeedsYou d={d} /></Card>
          </div>
          <div className="lg:col-span-4 lg:row-span-1"><Highlight d={d} /></div>

          <Card title="Which AI model answered" className="lg:col-span-5">
            <ModelAnswers models={d.models} theme={theme} />
          </Card>
          <Card title="Usage" className="lg:col-span-3"><Usage d={d} /></Card>
          <Card title="Testers" className="lg:col-span-4"><Testers tokens={d.tokens} /></Card>

          <Card title="Last errors" className="lg:col-span-12">
            {d.last_errors.length === 0 ? <Empty>No step failed in this period.</Empty> : (
              <ul className="space-y-1.5">
                {d.last_errors.map((e, i) => (
                  <li key={i} className="grid grid-cols-[8.5rem_6rem_minmax(0,1fr)] items-center gap-4 rounded-2xl bg-inset px-4 py-2.5 text-sm">
                    <span className="truncate tabular-nums text-ink-3" title={when(e.at)}>{shortWhen(e.at)}</span>
                    <span><Pill tone="solid">{STEP_NAMES[e.node] ?? e.node}</Pill></span>
                    <span className="truncate text-bad" title={`${e.run_id}: ${e.error ?? ""}`}>{e.error ?? "no message"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
