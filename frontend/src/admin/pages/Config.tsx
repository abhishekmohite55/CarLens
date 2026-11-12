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

const SECTIONS = ["upload", "models", "locate_video", "frames", "confirm", "photos", "plan", "search", "extract", "pricing", "dev", "auth", "access", "paths"];
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
    setVersions(null);
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
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-semibold">Config</h1>
        <span className="text-xs text-neutral-500">
          Active: version {loaded.id}, {when(loaded.saved_at)}{loaded.saved_by ? ` by ${loaded.saved_by}` : ""}{loaded.note ? ` · ${loaded.note}` : ""}
        </span>
      </div>
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <ul className="no-scrollbar -mx-4 flex shrink-0 gap-1 overflow-x-auto px-4 md:mx-0 md:block md:w-36 md:space-y-1 md:overflow-visible md:px-0">
          {sections.map((s) => {
            const changed = JSON.stringify(draft[s]) !== JSON.stringify(loaded.data[s]);
            const hasProblem = problems.some((p) => p.field.startsWith(`${s}.`) || p.field === s);
            return (
              <li key={s}>
                <button onClick={() => setSection(s)}
                  className={`w-full whitespace-nowrap rounded px-3 py-1 text-left font-mono text-sm ${section === s ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900"}`}>
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

      <div className="sticky bottom-0 mt-6 border-t border-neutral-800 bg-neutral-950 py-3">
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
          <Button onClick={async () => setVersions(versions ? null : (await api<{ versions: VersionRow[] }>("/api/admin/config/versions")).versions)}>
            {versions ? "Hide versions" : "Versions"}
          </Button>
          <Button onClick={importFile}>Import config.yaml</Button>
        </div>
        {versions && (
          <table className="mt-3 w-full text-sm">
            <tbody>
              {versions.map((v) => (
                <tr key={v.id} className="border-t border-neutral-900">
                  <td className="py-1 pr-4">v{v.id}{v.id === loaded.id && <span className="ml-2 text-xs text-green-400">active</span>}</td>
                  <td className="py-1 pr-4 text-neutral-400">{when(v.saved_at)}</td>
                  <td className="py-1 pr-4 text-neutral-400">{v.saved_by ?? "seed"}</td>
                  <td className="py-1 pr-4 text-neutral-400">{v.note}</td>
                  <td className="py-1">
                    {v.id !== loaded.id && (
                      <span className="flex gap-1"><Button onClick={() => view(v.id)}>View</Button><Button onClick={() => rollback(v.id)}>Roll back</Button></span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
