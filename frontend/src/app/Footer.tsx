// The footer of Landing, Home, the articles and the report (F10).
import { Link } from "react-router";

export function Footer() {
  return (
    <footer className="mx-auto mt-24 max-w-5xl border-t border-line px-4 py-10 sm:px-8">
      <nav className="text-label flex flex-wrap gap-x-6 gap-y-2 text-ink-2">
        <Link to="/how-it-works" className="hover:text-ink">How CarLens works</Link>
        <Link to="/questions" className="hover:text-ink">Questions</Link>
      </nav>
      <p className="text-small mt-4 text-ink-3">
        CarLens is a demo. Prices are estimates from public listings, not an offer or a certified valuation.
      </p>
    </footer>
  );
}
