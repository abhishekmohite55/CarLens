// Prompt editor (docs/platform/06-admin.md §6.3): each prompt is versioned; a save applies to runs that start from then on.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../shared/api";
import { MarketTag, useMarket, withMarket, type Market } from "../market";
import { Button, when } from "../ui";

// "number" = the prompt's own version (1, 2, 3 ...); "id" = the stored row, used to open or roll back a version
// Stage M0: every prompt belongs to one market (prompts/in/, prompts/us/); the header switch picks which are listed.
// file_differs (owner 28 Nov): the file in prompts/<market>/ is not the active text, so "Import file" would change it
type Listed = { name: string; market: Market; id: number; number: number; saved_at: string; saved_by: string | null; file_differs: boolean };
type ImportLine = { market: Market; name: string; changed: boolean; from: number | null; to: number };
type VersionRow = { id: number; number: number; saved_at: string; saved_by: string | null; note: string | null };
type Prompt = { name: string; market: Market; id: number; number: number; active: boolean; text: string; placeholders: string[]; versions: VersionRow[] };

const key = (p: { market: Market; name: string }) => `${p.market}/${p.name}`;
const promptPath = (market: Market, name: string, rest = "") => `/api/admin/prompts/${name}${rest}?market=${market}`;

export function Prompts() {
  const view = useMarket();
  const [list, setList] = useState<Listed[]>([]);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  async function open(market: Market, name: string, version?: number) {
    const data = await api<Prompt>(`${promptPath(market, name)}${version ? `&version=${version}` : ""}`);
    setPrompt(data);
    setText(data.text);
    setMessage(data.active ? "" : `Showing version ${data.number} (not active). Save to make this text active.`);
  }
  async function loadList() {
    const data = await api<{ prompts: Listed[] }>(withMarket("/api/admin/prompts", view));
    setList(data.prompts);
    return data.prompts;
  }
  useEffect(() => {
    setPrompt(null);
    loadList().then((prompts) => prompts[0] && open(prompts[0].market, prompts[0].name)).catch((e) => setMessage(e.message));
  }, [view]); // the header switch changed: list that market and open its first prompt

  async function run(action: () => Promise<{ version: number; changed?: boolean }>, done: (version: number, changed: boolean) => string) {
    if (!prompt) return;
    try {
      const { version, changed } = await action();
      await loadList();
      await open(prompt.market, prompt.name);
      setNote("");
      setMessage(done(version, changed !== false));
    } catch (e) {
      setMessage(e instanceof ApiError && e.problems?.length ? e.problems.map((p) => p.message).join("; ") : e instanceof Error ? e.message : "Not saved.");
    }
  }
  const dirty = prompt !== null && (text !== prompt.text || !prompt.active);
  const save = () => run(() => api(promptPath(prompt!.market, prompt!.name), { method: "PUT", body: { text, note: note || null } }),
    (v) => `Saved as version ${v}. Runs that start from now use it.`);
  const rollback = (v: VersionRow) => window.confirm(`Make version ${v.number} of ${key(prompt!)} active again (saved as a new version)?`)
    && run(() => api(promptPath(prompt!.market, prompt!.name, `/rollback/${v.id}`), { method: "POST" }), (n) => `Version ${v.number} is active again as version ${n}.`);
  const importFile = () => window.confirm(`Replace ${key(prompt!)} with the file from prompts/${prompt!.market}/ on the server (a new version only if the file is different)?`)
    && run(() => api(promptPath(prompt!.market, prompt!.name, "/import"), { method: "POST" }),
      (v, changed) => changed ? `File imported as version ${v}.` : `Already up to date: the file is the same as version ${v}.`);
  // owner 28 Nov: every prompt file at once (the market in the header, or all); only changed files get a new version
  const [importing, setImporting] = useState(false);
  async function importAll() {
    const where = view === "all" ? "both markets" : view === "us" ? "USA" : "India";
    if (dirty && !window.confirm("Drop your unsaved changes?")) return;
    if (!window.confirm(`Import every prompt file of ${where} from the server? Only files that changed get a new version.`)) return;
    setImporting(true);
    try {
      const r = await api<{ results: ImportLine[]; changed: number }>(withMarket("/api/admin/prompts/import-all", view), { method: "POST" });
      const changed = r.results.filter((x) => x.changed);
      await loadList();
      if (prompt) await open(prompt.market, prompt.name);  // before the message: open() clears it
      setMessage(changed.length
        ? `${changed.length} updated: ${changed.map((x) => `${x.market}/${x.name} v${x.from ?? "–"} → v${x.to}`).join(", ")}. ${r.results.length - changed.length} already up to date.`
        : `All ${r.results.length} prompts already up to date.`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  }
  const pick = (value: string) => {
    const [market, name] = value.split("/") as [Market, string];
    if (name && (!dirty || window.confirm("Drop your unsaved changes?"))) void open(market, name);
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl sm:text-3xl font-light tracking-tight text-ink">Prompts</h1>
        <span className="ml-auto flex items-center gap-2">
          {list.some((p) => p.file_differs) && (
            <span className="text-xs text-amber-400">{list.filter((p) => p.file_differs).length} file(s) changed</span>
          )}
          <Button disabled={importing} onClick={() => void importAll()}>{importing ? "Importing…" : "Import all files"}</Button>
        </span>
      </div>
      {message && !prompt && <p className="mb-3 text-sm text-neutral-400">{message}</p>}
      {list.length === 0 && !message && (
        <p className="mb-4 text-sm text-neutral-500">
          {view === "us" ? "No US prompts yet: prompts/us/ is empty (US prompts come in stages U3–U5)." : "No prompts."}
        </p>
      )}
      <div className="flex flex-col gap-4 md:flex-row md:gap-6">
        <select
          className="block md:hidden rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-200"
          value={prompt ? key(prompt) : ""}
          onChange={(e) => pick(e.target.value)}
        >
          {list.map((p) => <option key={key(p)} value={key(p)}>{view === "all" ? `${p.market.toUpperCase()} · ` : ""}{p.name} v{p.number}{p.file_differs ? " • file changed" : ""}</option>)}
        </select>
        <ul className="hidden md:block shrink-0 md:w-64 md:space-y-1">
          {list.map((p) => (
            <li key={key(p)}>
              <button onClick={() => pick(key(p))}
                className={`w-full whitespace-nowrap rounded px-3 py-1 text-left font-mono text-xs ${prompt && key(prompt) === key(p) ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900"}`}>
                {p.name} <span className="text-neutral-600">v{p.number}</span><MarketTag market={p.market} />
                {p.file_differs && <span className="ml-1.5 text-amber-400" title="The file on the server differs from this version: Import file to use it">● file changed</span>}
              </button>
            </li>
          ))}
        </ul>
        {prompt && (
          <div className="min-w-0 flex-1">
            <p className="mb-2 font-mono text-xs text-neutral-400">prompts/{prompt.market}/{prompt.name} · {prompt.market === "us" ? "US" : "India"}</p>
            {prompt.placeholders.length > 0 && (
              <p className="mb-2 text-xs text-neutral-500">
                Placeholders filled in by the pipeline: {prompt.placeholders.map((p) => `{${p}}`).join(", ")}. Write {"{{"} and {"}}"} for literal braces.
              </p>
            )}
            <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              className="h-[60vh] w-full rounded border border-neutral-700 bg-neutral-900 p-3 font-mono text-sm text-neutral-100" />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input className="w-72 max-w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm" placeholder="Note for this version (optional)"
                value={note} onChange={(e) => setNote(e.target.value)} />
              <Button kind="primary" disabled={!dirty} onClick={save}>Save as new version</Button>
              <Button disabled={!dirty} onClick={() => open(prompt.market, prompt.name)}>Discard</Button>
              <span className="flex-1 text-sm text-neutral-400">{message}</span>
              <Button onClick={importFile}>Import file</Button>
            </div>
            {/* Mobile version list */}
            <div className="sm:hidden mt-4 divide-y divide-neutral-900">
              {prompt.versions.map((v, i) => (
                <div key={v.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <div>
                    <span className="text-neutral-200">v{v.number}</span>
                    {i === 0 && <span className="ml-1.5 text-xs text-green-400">active</span>}
                    <span className="ml-2 text-xs text-neutral-500">{when(v.saved_at)}</span>
                  </div>
                  {i > 0 && (
                    <span className="flex shrink-0 gap-1">
                      <Button onClick={() => open(prompt.market, prompt.name, v.id)}>View</Button>
                      <Button onClick={() => rollback(v)}>Roll back</Button>
                    </span>
                  )}
                </div>
              ))}
            </div>
            {/* Desktop version table */}
            <div className="hidden sm:block">
            <table className="mt-4 w-full text-sm">
              <tbody>
                {prompt.versions.map((v, i) => (
                  <tr key={v.id} className="border-t border-neutral-900">
                    <td className="py-1 pr-4">v{v.number}{i === 0 && <span className="ml-2 text-xs text-green-400">active</span>}</td>
                    <td className="py-1 pr-4 text-neutral-400">{when(v.saved_at)}</td>
                    <td className="py-1 pr-4 text-neutral-400">{v.saved_by ?? "seed"}</td>
                    <td className="py-1 pr-4 text-neutral-400">{v.note}</td>
                    <td className="py-1">
                      {i > 0 && (
                        <span className="flex gap-1"><Button onClick={() => open(prompt.market, prompt.name, v.id)}>View</Button><Button onClick={() => rollback(v)}>Roll back</Button></span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
