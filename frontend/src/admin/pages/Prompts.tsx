// Prompt editor (docs/platform/06-admin.md §6.3): each prompt is versioned; a save applies to runs that start from then on.
import { useEffect, useState } from "react";
import { api, ApiError } from "../../shared/api";
import { Button, when } from "../ui";

// "number" = the prompt's own version (1, 2, 3 ...); "id" = the stored row, used to open or roll back a version
type Listed = { name: string; id: number; number: number; saved_at: string; saved_by: string | null };
type VersionRow = { id: number; number: number; saved_at: string; saved_by: string | null; note: string | null };
type Prompt = { name: string; id: number; number: number; active: boolean; text: string; placeholders: string[]; versions: VersionRow[] };

export function Prompts() {
  const [list, setList] = useState<Listed[]>([]);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  async function open(name: string, version?: number) {
    const data = await api<Prompt>(`/api/admin/prompts/${name}${version ? `?version=${version}` : ""}`);
    setPrompt(data);
    setText(data.text);
    setMessage(data.active ? "" : `Showing version ${data.number} (not active). Save to make this text active.`);
  }
  async function loadList() {
    const data = await api<{ prompts: Listed[] }>("/api/admin/prompts");
    setList(data.prompts);
    return data.prompts;
  }
  useEffect(() => {
    loadList().then((prompts) => prompts[0] && open(prompts[0].name)).catch((e) => setMessage(e.message));
  }, []);

  async function run(action: () => Promise<{ version: number }>, done: (version: number) => string) {
    if (!prompt) return;
    try {
      const { version } = await action();
      await loadList();
      await open(prompt.name);
      setNote("");
      setMessage(done(version));
    } catch (e) {
      setMessage(e instanceof ApiError && e.problems?.length ? e.problems.map((p) => p.message).join("; ") : e instanceof Error ? e.message : "Not saved.");
    }
  }
  const dirty = prompt !== null && (text !== prompt.text || !prompt.active);
  const save = () => run(() => api(`/api/admin/prompts/${prompt!.name}`, { method: "PUT", body: { text, note: note || null } }),
    (v) => `Saved as version ${v}. Runs that start from now use it.`);
  const rollback = (v: VersionRow) => window.confirm(`Make version ${v.number} of ${prompt!.name} active again (saved as a new version)?`)
    && run(() => api(`/api/admin/prompts/${prompt!.name}/rollback/${v.id}`, { method: "POST" }), (n) => `Version ${v.number} is active again as version ${n}.`);
  const importFile = () => window.confirm(`Replace ${prompt!.name} with the file from prompts/ on the server (saved as a new version)?`)
    && run(() => api(`/api/admin/prompts/${prompt!.name}/import`, { method: "POST" }), (v) => `File imported as version ${v}.`);

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Prompts</h1>
      <div className="flex gap-6">
        <ul className="w-56 shrink-0 space-y-1">
          {list.map((p) => (
            <li key={p.name}>
              <button onClick={() => (!dirty || window.confirm("Drop your unsaved changes?")) && open(p.name)}
                className={`w-full rounded px-3 py-1 text-left font-mono text-xs ${prompt?.name === p.name ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900"}`}>
                {p.name} <span className="text-neutral-600">v{p.number}</span>
              </button>
            </li>
          ))}
        </ul>
        {prompt && (
          <div className="min-w-0 flex-1">
            {prompt.placeholders.length > 0 && (
              <p className="mb-2 text-xs text-neutral-500">
                Placeholders filled in by the pipeline: {prompt.placeholders.map((p) => `{${p}}`).join(", ")}. Write {"{{"} and {"}}"} for literal braces.
              </p>
            )}
            <textarea value={text} onChange={(e) => setText(e.target.value)} spellCheck={false}
              className="h-[60vh] w-full rounded border border-neutral-700 bg-neutral-900 p-3 font-mono text-sm text-neutral-100" />
            <div className="mt-2 flex items-center gap-2">
              <input className="w-72 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm" placeholder="Note for this version (optional)"
                value={note} onChange={(e) => setNote(e.target.value)} />
              <Button kind="primary" disabled={!dirty} onClick={save}>Save as new version</Button>
              <Button disabled={!dirty} onClick={() => open(prompt.name)}>Discard</Button>
              <span className="flex-1 text-sm text-neutral-400">{message}</span>
              <Button onClick={importFile}>Import file</Button>
            </div>
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
                        <span className="flex gap-1"><Button onClick={() => open(prompt.name, v.id)}>View</Button><Button onClick={() => rollback(v)}>Roll back</Button></span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
