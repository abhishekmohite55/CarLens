// The run page arrives in stage F5. Until then this placeholder opens the run's live events (which also starts a run
// that has not started yet, as the backend does) and shows the latest one, so F4 can be tested end to end.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { Lens } from "./Lens";

type Event = { node: string; type: string; data?: { summary?: string; error?: string; status?: string } };

export function RunSoon() {
  const { id } = useParams();
  const [last, setLast] = useState<Event | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const source = new EventSource(`/api/runs/${id}/events`);
    source.onmessage = (m) => setLast(JSON.parse(m.data));
    source.onerror = () => {
      fetch(`/api/runs/${id}`).then((r) => { if (r.status === 404) { setMissing(true); source.close(); } });
    };
    return () => source.close();
  }, [id]);

  const detail = last?.data?.summary ?? last?.data?.error ?? last?.data?.status ?? "";
  return (
    <div className="flex min-h-svh items-center justify-center bg-canvas px-4 text-ink">
      <Lens scene={missing ? "missing" : "run"} radius={32} className="w-[min(92vw,26rem)]">
        <div className="space-y-3 p-6">
          {missing ? (
            <p className="text-heading">This run does not exist.</p>
          ) : (
            <>
              <p className="text-heading">Run started.</p>
              <p className="text-body opacity-80">The full run page arrives in the next stage.</p>
              <p className="text-small tabular-nums opacity-75">
                {last ? `Latest: ${last.node}, ${last.type}${detail ? `: ${detail}` : ""}` : "Connecting"}
              </p>
            </>
          )}
          <Link to="/home" className="text-label inline-block rounded-full bg-canvas px-5 py-3 text-ink">Back to Home</Link>
        </div>
      </Lens>
    </div>
  );
}
