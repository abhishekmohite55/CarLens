// Small building blocks shared by the admin pages.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { ApiError } from "../shared/api";

export function Button({ children, onClick, kind = "plain", disabled }: {
  children: ReactNode; onClick: () => void; kind?: "plain" | "primary" | "danger"; disabled?: boolean;
}) {
  const colors = {
    plain: "bg-neutral-800 text-neutral-200 hover:bg-neutral-700",
    primary: "bg-blue-600 text-white hover:bg-blue-500",
    danger: "bg-red-700 text-white hover:bg-red-600",
  }[kind];
  return (
    <button disabled={disabled} onClick={onClick} className={`rounded-full px-3 py-1 text-xs transition-colors disabled:opacity-40 ${colors}`}>
      {children}
    </button>
  );
}

// Wording shown for stored status values (owner, 12 Nov).
const LABELS: Record<string, string> = { awaiting_confirm: "awaiting confirmation", partial: "stopped" };

export function Badge({ text }: { text: string }) {
  const colors: Record<string, string> = {
    pending: "bg-amber-900 text-amber-200", approved: "bg-green-900 text-green-200", rejected: "bg-red-900 text-red-200",
    running: "bg-blue-900 text-blue-200", uploaded: "bg-blue-900 text-blue-200", awaiting_confirm: "bg-purple-900 text-purple-200",
    complete: "bg-green-900 text-green-200", partial: "bg-neutral-700 text-neutral-200", failed: "bg-red-900 text-red-200",
    done: "bg-green-900 text-green-200", skipped: "bg-neutral-700 text-neutral-300", admin: "bg-blue-900 text-blue-200",
  };
  return <span className={`rounded-full px-2.5 py-0.5 text-xs ${colors[text] ?? "bg-neutral-800 text-neutral-300"}`}>{LABELS[text] ?? text}</span>;
}

export function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

/** Load data, reload on demand, and run actions that show their error message. */
export function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    try {
      setData(await load());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load.");
    }
  }, [load]);
  useEffect(() => {
    reload();
  }, [reload]);
  const act = useCallback(async (action: () => Promise<unknown>) => {
    try {
      await action();
      await reload();
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : "That did not work.");
    }
  }, [reload]);
  return { data, error, reload, act };
}

export const th = "border-b border-neutral-800 px-3 py-2 text-left text-xs font-medium text-neutral-500";
export const td = "border-b border-neutral-900 px-3 py-2 align-top text-sm";
