// The footer of Landing, Home, the articles and the report (F10).
import { Link } from "react-router";

export function Footer() {
  return (
    <footer className="mx-auto mt-24 max-w-5xl border-t border-line px-4 pb-safe pt-10 sm:px-8">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-heading">CarLens</p>
          <p className="text-body mt-1.5 text-ink-2">Video inspection for used cars.</p>
        </div>
        <nav className="text-label flex flex-wrap gap-x-6 gap-y-2 text-ink-2 sm:pt-0.5">
          <Link to="/how-it-works" className="hover:text-ink">How it works</Link>
          <Link to="/questions" className="hover:text-ink">Questions</Link>
        </nav>
      </div>
      <p className="text-small mt-8 text-ink-3">
        CarLens is a demo. Prices are estimates from public listings, not an offer or a certified valuation.
      </p>
    </footer>
  );
}
