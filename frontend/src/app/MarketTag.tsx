// Owner 28 Nov: the CarLens logo with a small market tag at its bottom-right, so the user knows which version
// (India or US) they are using. Colours as in admin: India saffron (amber-500), US indigo (indigo-500).
import { Link } from "react-router";
import type { Market } from "./market";

const TAG: Record<Market, { text: string; color: string; title: string }> = {
  in: { text: "IN", color: "#f59e0b", title: "India version" },
  us: { text: "US", color: "#6366f1", title: "US version" },
};

/** market undefined: not known yet, the logo shows without a tag. */
export function Logo({ market, to = "/home" }: { market?: Market; to?: string }) {
  const tag = market ? TAG[market] : undefined;
  return (
    <Link to={to} className="text-heading relative inline-block pr-5" aria-label={tag ? `CarLens, ${tag.title}` : "CarLens"}>
      CarLens
      {tag && (
        <span title={tag.title} style={{ backgroundColor: tag.color }}
          className="absolute -right-1 -bottom-1.5 rounded-full px-1.5 py-px text-[0.6rem] leading-tight font-semibold tracking-wide text-white">
          {tag.text}
        </span>
      )}
    </Link>
  );
}
