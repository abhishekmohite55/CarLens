// F10: when the server or the network is gone, say so plainly instead of a blank page (ERR-5).
import { useEffect, useState, type ReactNode } from "react";
import { Lens } from "./Lens";

/** Checks once that the backend answers; a network error or a 5xx shows the "not reachable" card. */
export function Reachable({ children }: { children: ReactNode }) {
  const [down, setDown] = useState(false);
  useEffect(() => {
    fetch("/api/auth/me", { cache: "no-store" }).then((r) => setDown(r.status >= 500)).catch(() => setDown(true));
  }, []);
  if (!down) return children;
  return (
    <div className="flex min-h-svh items-center justify-center bg-canvas px-4 text-ink">
      <Lens scene="down" radius={32} className="w-[min(92vw,24rem)]">
        <div className="space-y-3 p-6">
          <p className="text-heading">CarLens is not reachable right now.</p>
          <p className="text-body opacity-80">The demo runs on a laptop that may be off. Try again later.</p>
          <button onClick={() => window.location.reload()} className="text-label rounded-full bg-canvas px-5 py-3 text-ink">Try again</button>
        </div>
      </Lens>
    </div>
  );
}

/** A thin line at the top while the device is offline. */
export function OfflineLine() {
  const [offline, setOffline] = useState(!navigator.onLine);
  useEffect(() => {
    const on = () => setOffline(false), off = () => setOffline(true);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  if (!offline) return null;
  return (
    <p role="status" className="text-small fixed inset-x-0 top-0 z-50 bg-warn-soft px-4 py-2 text-center text-warn-text">
      You are offline. The page will update when you reconnect.
    </p>
  );
}
