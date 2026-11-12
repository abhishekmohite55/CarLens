// Table browser (docs/platform/06-admin.md §6.7): every table read-only; changes go through the other pages.
import { useCallback, useEffect, useState } from "react";
import { api } from "../../shared/api";
import { Button, td, th, useLoad } from "../ui";

type TableInfo = { name: string; rows: number; columns: string[] };
type Page = { table: string; columns: string[]; page: number; page_size: number; total: number; rows: Record<string, unknown>[] };

const input = "rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

export function Tables() {
  const loadList = useCallback(() => api<{ tables: TableInfo[] }>("/api/admin/tables"), []);
  const { data: list, error: listError } = useLoad(loadList);
  const [table, setTable] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<string | null>(null);
  const [desc, setDesc] = useState(true);
  const [search, setSearch] = useState("");
  const [column, setColumn] = useState("");
  const [value, setValue] = useState("");
  const [data, setData] = useState<Page | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!table) return;
    const params = new URLSearchParams({ page: String(page), desc: String(desc) });
    if (sort) params.set("sort", sort);
    if (search) params.set("search", search);
    if (column) { params.set("column", column); params.set("value", value); }
    const timer = window.setTimeout(() => {
      api<Page>(`/api/admin/tables/${table}?${params}`).then((p) => { setData(p); setError(""); }).catch((e) => setError(e.message));
    }, 300); // typing in the search box: one request after a pause
    return () => window.clearTimeout(timer);
  }, [table, page, sort, desc, search, column, value]);

  function open(name: string) {
    setTable(name); setPage(1); setSort(null); setDesc(true); setSearch(""); setColumn(""); setValue(""); setData(null);
  }
  function sortBy(col: string) {
    if (sort === col) setDesc(!desc); else { setSort(col); setDesc(true); }
    setPage(1);
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="flex gap-6">
      <ul className="w-52 shrink-0 space-y-1">
        {listError && <li className="text-sm text-red-400">{listError}</li>}
        {list?.tables.map((t) => (
          <li key={t.name}>
            <button onClick={() => open(t.name)}
              className={`flex w-full justify-between rounded px-3 py-1 text-left font-mono text-xs ${table === t.name ? "bg-neutral-800 text-white" : "text-neutral-400 hover:bg-neutral-900"}`}>
              <span>{t.name}</span><span className="text-neutral-600">{t.rows}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0 flex-1">
        <h1 className="mb-1 text-xl font-semibold">{table ?? "Tables"}</h1>
        <p className="mb-3 text-xs text-neutral-500">Read-only. Secret columns show •••. Long values are cut.</p>
        {table && data && (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input className={`${input} w-64`} placeholder="Search text columns" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
              <select className={input} value={column} onChange={(e) => { setColumn(e.target.value); setPage(1); }}>
                <option value="">filter column…</option>
                {data.columns.map((c) => <option key={c}>{c}</option>)}
              </select>
              {column && <input className={`${input} w-48`} placeholder="contains" value={value} onChange={(e) => { setValue(e.target.value); setPage(1); }} />}
              <span className="flex-1 text-right text-sm text-neutral-400">{data.total} rows</span>
              <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</Button>
              <span className="text-sm text-neutral-400">{page} / {pages}</span>
              <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>›</Button>
            </div>
            {error && <p className="mb-2 text-sm text-red-400">{error}</p>}
            <div className="overflow-x-auto">
              <table className="w-max min-w-full">
                <thead>
                  <tr>
                    {data.columns.map((c) => (
                      <th key={c} className={`${th} cursor-pointer whitespace-nowrap hover:text-neutral-200`} onClick={() => sortBy(c)}>
                        {c}{sort === c ? (desc ? " ↓" : " ↑") : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r, i) => (
                    <tr key={i}>
                      {data.columns.map((c) => (
                        <td key={c} className={`${td} max-w-md truncate font-mono text-xs`} title={show(r[c])}>{show(r[c])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
