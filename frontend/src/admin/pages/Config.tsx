// Config editor (docs/platform/06-admin.md §6.1): every field of the config, one section per block.
// Fields are drawn from the data itself (number, text, yes/no, list, model chain), so a new config field
// shows up here without a code change. A save is checked by the backend, becomes a new version and applies
// to runs that start from then on.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../shared/api";
import { Button, when } from "../ui";
import { ChainEditor, EntryFields, type ModelEntry } from "./ChainEditor";

type Data = Record<string, Record<string, unknown>>;
type Version = { id: number; active: boolean; saved_at: string; saved_by: string | null; note: string | null; data: Data };
type Loaded = Version & { options: { stop_after: string[]; providers: string[] } };
type VersionRow = { id: number; saved_at: string; saved_by: string | null; note: string | null };
type Problem = { field: string; message: string };

const SECTIONS = ["upload", "models", "locate_video", "frames", "confirm", "photos", "plan", "search", "extract", "pricing", "dev", "auth", "access", "storage", "maintenance", "paths"];
const READ_ONLY = ["paths"]; // moving run folders under a live app would lose runs
const LEVELS = ["", "minimal", "low", "medium", "high"];
// Fields with a fixed set of values ("" = empty = default)
const CHOICES: Record<string, string[]> = {
  "models.locate_media_resolution": ["low", "medium", "high"],
  "models.verify_media_resolution": ["low", "medium", "high"],
  "models.locate_thinking_level": LEVELS,
  "models.verify_thinking_level": LEVELS,
  "models.extract_reasoning_effort": ["", "none", "minimal", "low", "medium", "high"],
  "search.depth": ["basic", "advanced"],
};
const HINTS: Record<string, string> = {
  "dev.stop_after": "The pipeline ends after this step. Empty = run everything.",
  "models.verify_chain": "Tried top to bottom; the next model runs on an error, a bad answer or a timeout.",
  "models.photos_chain": "Empty = use the verify chain.",
  "models.locate": "Video call (Google SDK). The fallback model is tried on a 503 / 500 / 504 / 429.",
  "upload.max_duration_sec": "Longest video accepted, in seconds.",
  "access.default_tokens": "Runs given when you approve a request.",
  "upload.max_parallel": "Uploads received and checked at once (users). One more gets \"busy\".",
  "upload.repeat_warn_count": "Same-video or refused uploads by one user that show them under \"Needs you\" on the dashboard.",
  "upload.repeat_window_min": "Minutes over which repeated uploads are counted.",
  "locate_video.shrink_timeout_sec": "If shrinking the video takes longer, locate stops with a clear message (the original is never sent).",
  "photos.max_pixels": "Photos larger than this many pixels are refused before they are opened (50000000 = 50 MP).",
  "photos.max_parallel": "Photos decoded at once; more wait their turn.",
  "access.free_resumes_per_run": "A user may press Resume while the run has failed at most this many times. The admin has no limit.",
  "access.max_active_runs": "Runs uploaded or working at once (all users). Above it, users are asked to try again in a few minutes.",
  "access.max_event_streams": "Live run pages open at once (all users).",
  "models.max_calls_in_flight": "Model calls still running at once, also ones past their timeout. More are refused.",
  "auth.client_ip_header": "Empty on the laptop. On AWS: X-Viewer-IP (the visitor's address, from CloudFront).",
  "maintenance.confirm_grace_min": "During a deploy, runs waiting at confirm may still be confirmed this many minutes.",
  "maintenance.stale_confirm_min": "A run waiting at confirm longer than this many minutes never holds a deploy back.",
  "maintenance.auto_off_min": "Safety net: maintenance switched on longer ago than this counts as off.",
  "maintenance.max_wait_min": "A deploy waits at most this many minutes for working runs, then deploys anyway.",
  "storage.local_keep_days": "On the server with S3: finished runs untouched this long keep only the S3 copy.",
};

const input = "rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm text-neutral-100";

function isChain(key: string, value: unknown): value is ModelEntry[] {
  return Array.isArray(value) && (key.endsWith("_chain") || (value.length > 0 && typeof value[0] === "object"));
}

function Field({ path, name, value, saved, options, readOnly, onChange }: {
  path: string; name: string; value: unknown; saved: unknown; options: Loaded["options"]; readOnly: boolean; onChange: (value: unknown) => void;
}) {
  const choices = path === "dev.stop_after" ? ["", ...options.stop_after] : CHOICES[path];
  let control;
  if (choices) {
    control = (
      <select className={input} disabled={readOnly} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || null)}>
        {choices.map((c) => <option key={c} value={c}>{c || "(empty)"}</option>)}
      </select>
    );
  } else if (isChain(name, value)) {
    control = <ChainEditor entries={value} providers={options.providers} onChange={onChange} />;
  } else if (value !== null && typeof value === "object" && !Array.isArray(value) && "provider" in value) {
    control = (
      <div className="flex items-center gap-2">
        <EntryFields entry={value as ModelEntry} providers={options.providers} onChange={onChange} withFallback />
      </div>
    );
  } else if (Array.isArray(value)) {
    control = (
      <textarea className={`${input} w-full font-mono`} disabled={readOnly} rows={Math.max(2, value.length + 1)} value={value.join("\n")}
        title="One per line" onChange={(e) => onChange(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))} />
    );
  } else if (typeof value === "boolean") {
    control = <input type="checkbox" disabled={readOnly} checked={value} onChange={(e) => onChange(e.target.checked)} />;
  } else if (typeof saved === "number" || typeof value === "number") {
    // a cleared number box holds "" until a number is typed; saving it empty is refused with the field name
    control = (
      <input className={`${input} w-40`} type="number" step="any" disabled={readOnly} value={(value as number | string | null) ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />
    );
  } else {
    // text; an optional field (saved empty) goes back to empty (null) when the box is cleared
    control = (
      <input className={`${input} w-80 max-w-full`} disabled={readOnly} value={(value as string | null) ?? ""}
        onChange={(e) => onChange(saved === null ? e.target.value || null : e.target.value)} />
    );
  }
  return (
    <div className="border-b border-neutral-900 py-3">
      <div className="mb-1 font-mono text-sm text-neutral-300">{name}</div>
      {HINTS[path] && <div className="mb-2 text-xs text-neutral-500">{HINTS[path]}</div>}
      {control}
    </div>
  );
}

export function Config() {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [draft, setDraft] = useState<Data | null>(null);
  const [section, setSection] = useState("upload");
  const [note, setNote] = useState("");
  const [problems, setProblems] = useState<Problem[]>([]);
  const [message, setMessage] = useState("");
  const [versions, setVersions] = useState<VersionRow[] | null>(null);
  const [shown, setShown] = useState(0); // bumped whenever the whole draft is replaced, so list editors start fresh

  async function load() {
    const data = await api<Loaded>("/api/admin/config");
    setLoaded(data);
    setDraft(structuredClone(data.data));
    setShown((n) => n + 1);
    setProblems([]);
    // Load versions independently; a failure only leaves the list empty.
    api<{ versions: VersionRow[] }>("/api/admin/config/versions")
      .then((r) => setVersions(r.versions))
      .catch(() => setVersions([]));
  }
  useEffect(() => {
    load().catch((e) => setMessage(e.message));
  }, []);

  if (!loaded || !draft) return <p className="text-sm text-neutral-500">{message || "Loading…"}</p>;
  const dirty = JSON.stringify(draft) !== JSON.stringify(loaded.data);

  async function run(action: () => Promise<{ version: number }>, done: (version: number) => string) {
    setMessage("");
    try {
      const { version } = await action();
      await load();
      setNote("");
      setMessage(done(version));
    } catch (e) {
      setProblems(e instanceof ApiError ? e.problems ?? [] : []);
      setMessage(e instanceof Error && !(e instanceof ApiError && e.problems) ? e.message : "Not saved: fix the fields below.");
    }
  }
  const save = () => run(() => api("/api/admin/config", { method: "PUT", body: { data: draft, note: note || null } }),
    (v) => `Saved as version ${v}. Runs that start from now use it.`);
  const rollback = (id: number) => window.confirm(`Make version ${id} the active config again (saved as a new version)?`)
    && run(() => api(`/api/admin/config/rollback/${id}`, { method: "POST" }), (v) => `Version ${id} is active again as version ${v}.`);
  const importFile = () => window.confirm("Replace the active config with config.yaml from the server (saved as a new version)?")
    && run(() => api("/api/admin/config/import", { method: "POST" }), (v) => `config.yaml imported as version ${v}.`);
  async function view(id: number) {
    setDraft(structuredClone((await api<Version>(`/api/admin/config/versions/${id}`)).data));
    setShown((n) => n + 1);
    setMessage(`Showing version ${id} (not saved). Save to make it active, or Discard.`);
  }

  const fields = draft[section] ?? {};
  const sections = [...SECTIONS.filter((s) => s in draft), ...Object.keys(draft).filter((s) => !SECTIONS.includes(s))];
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="font-display text-3xl font-light tracking-tight text-ink">Config</h1>
        <span className="flex items-center gap-1.5 rounded-full bg-green-900/50 px-3 py-1 text-xs text-green-300">
          <span className="h-1.5 w-1.5 rounded-full bg-green-400" aria-hidden="true" />
          Active: v{loaded.id} · {when(loaded.saved_at)}{loaded.saved_by ? ` · ${loaded.saved_by}` : ""}{loaded.note ? ` · ${loaded.note}` : ""}
        </span>
      </div>

      {/* Settings card */}
      <div className="mb-6 overflow-hidden rounded-2xl bg-card shadow-card">
        <div className="flex flex-col gap-4 p-4 md:flex-row md:gap-6 md:p-6">
          <ul className="no-scrollbar -mx-4 flex shrink-0 gap-1 overflow-x-auto px-4 md:mx-0 md:block md:w-36 md:space-y-1 md:overflow-visible md:px-0">
            {sections.map((s) => {
              const changed = JSON.stringify(draft[s]) !== JSON.stringify(loaded.data[s]);
              const hasProblem = problems.some((p) => p.field.startsWith(`${s}.`) || p.field === s);
              return (
                <li key={s}>
                  <button onClick={() => setSection(s)}
                    className={`w-full whitespace-nowrap rounded px-3 py-1 text-left font-mono text-sm transition-colors ${section === s ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"}`}>
                    {s}{changed && <span className="text-amber-400"> •</span>}{hasProblem && <span className="text-red-400"> !</span>}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="min-w-0 flex-1">
            {READ_ONLY.includes(section) && <p className="mb-2 text-xs text-neutral-500">Read-only.</p>}
            {Object.entries(fields).map(([name, value]) => (
              <Field key={`${shown}.${section}.${name}`} path={`${section}.${name}`} name={name} value={value}
                saved={loaded.data[section]?.[name]} options={loaded.options}
                readOnly={READ_ONLY.includes(section)}
                onChange={(changed) => setDraft({ ...draft, [section]: { ...draft[section], [name]: changed } })} />
            ))}
          </div>
        </div>
        <div className="border-t border-neutral-800 px-4 py-3 md:px-6">
          {problems.length > 0 && (
            <ul className="mb-2 text-sm text-red-400">
              {problems.map((p, i) => <li key={i}><span className="font-mono">{p.field}</span>: {p.message}</li>)}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <input className={`${input} w-72 max-w-full`} placeholder="Note for this version (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button kind="primary" disabled={!dirty} onClick={save}>Save as new version</Button>
            <Button disabled={!dirty} onClick={() => { setDraft(structuredClone(loaded.data)); setShown((n) => n + 1); setProblems([]); setMessage(""); }}>Discard</Button>
            <span className="flex-1 text-sm text-neutral-400">{message}</span>
            <Button onClick={importFile}>Import config.yaml</Button>
          </div>
        </div>
      </div>

      {/* Version list card */}
      {versions !== null && (
        <div className="rounded-2xl bg-card shadow-card">
          <div className="border-b border-neutral-800 px-4 py-3 md:px-6">
            <h2 className="text-sm font-semibold text-neutral-300">Version history</h2>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {versions.length === 0 ? (
                <tr><td className="px-4 py-3 text-neutral-500">No versions yet.</td></tr>
              ) : versions.map((v) => (
                <tr key={v.id} className="border-t border-neutral-900 first:border-0">
                  <td className="py-2 pl-4 pr-4">v{v.id}{v.id === loaded.id && <span className="ml-2 text-xs text-green-400">active</span>}</td>
                  <td className="py-2 pr-4 text-neutral-400">{when(v.saved_at)}</td>
                  <td className="py-2 pr-4 text-neutral-400">{v.saved_by ?? "seed"}</td>
                  <td className="py-2 pr-4 text-neutral-400">{v.note}</td>
                  <td className="py-2 pr-4">
                    {v.id !== loaded.id && (
                      <span className="flex gap-1">
                        <button onClick={() => view(v.id)} title="View this version"
                          className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <ellipse cx="8" cy="8" rx="6.5" ry="4.5" />
                            <circle cx="8" cy="8" r="1.75" fill="currentColor" stroke="none" />
                          </svg>
                          <span className="sr-only">View</span>
                        </button>
                        <button onClick={() => rollback(v.id)} title="Roll back to this version"
                          className="rounded p-1.5 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-neutral-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d="M2.5 8a5.5 5.5 0 1 0 1.1-3.3" />
                            <polyline points="2.5 2.5 2.5 6 6 6" />
                          </svg>
                          <span className="sr-only">Roll back</span>
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
