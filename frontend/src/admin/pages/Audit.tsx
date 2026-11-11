import { useCallback } from "react";
import { api } from "../../shared/api";
import { td, th, useLoad, when } from "../ui";

type Entry = { id: number; at: string; admin: string | null; action: string; target: string | null; details: unknown };

export function Audit() {
  const load = useCallback(() => api<{ entries: Entry[] }>("/api/admin/audit"), []);
  const { data, error } = useLoad(load);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Audit log</h1>
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
      <table className="w-full">
        <thead>
          <tr>{["When", "Admin", "Action", "Target", "Details"].map((h) => <th key={h} className={th}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {data?.entries.map((e) => (
            <tr key={e.id}>
              <td className={td}>{when(e.at)}</td>
              <td className={td}>{e.admin ?? "—"}</td>
              <td className={td}>{e.action}</td>
              <td className={td}>{e.target}</td>
              <td className={`${td} font-mono text-xs text-neutral-400`}>{JSON.stringify(e.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.entries.length === 0 && <p className="mt-4 text-sm text-neutral-500">No admin changes yet.</p>}
    </div>
  );
}
