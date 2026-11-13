// Sign in and Request access arrive in stage F3. Until then this placeholder keeps the landing page's links working.
import { Link } from "react-router";
import { Lens } from "./Lens";

export function Door({ title, text = "This screen arrives in the next stage." }: { title: string; text?: string }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-canvas px-4">
      <Lens scene={title} radius={32} className="w-[min(92vw,24rem)]">
        <div className="p-6">
          <p className="text-title">{title}</p>
          <p className="text-body mt-3 opacity-80">{text}</p>
          <Link to="/" className="text-label mt-6 inline-block rounded-full bg-canvas px-5 py-3 text-ink">Back to CarLens</Link>
        </div>
      </Lens>
    </div>
  );
}
