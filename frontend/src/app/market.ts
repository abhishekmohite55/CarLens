// US market in the app (docs/backend/07-us-market.md §13). The visitor's market comes from GET /api/config; a run's
// market from its meta.json. Money is always formatted by the RUN's currency, never by the visitor's market.

export type Market = "in" | "us";
export type UsConfig = { top_states: string[]; states: { code: string; name: string }[]; state_guess: string | null };

/** The admin's own switch on Home (sent as ?market=; ignored by the server for everyone else). */
const ADMIN_KEY = "carlens.app.market";
export function adminMarket(): Market | null {
  try {
    const m = localStorage.getItem(ADMIN_KEY);
    return m === "in" || m === "us" ? m : null;
  } catch {
    return null;
  }
}
export function setAdminMarket(m: Market) {
  try { localStorage.setItem(ADMIN_KEY, m); } catch { /* private mode: not remembered */ }
}

/** "$24,995" for a US run, "₹4,95,000" for an India run. */
export function money(v: number, currency?: string) {
  return currency === "USD" ? `$${Math.round(v).toLocaleString("en-US")}` : `₹${Math.round(v).toLocaleString("en-IN")}`;
}

// --- VIN: same rules and messages as backend/app/vin/check.py (the server checks again) ---
const VALUES: Record<string, number> = { A: 1, B: 2, C: 3, D: 4, E: 5, F: 6, G: 7, H: 8, J: 1, K: 2, L: 3, M: 4, N: 5, P: 7, R: 9,
  S: 2, T: 3, U: 4, V: 5, W: 6, X: 7, Y: 8, Z: 9 };
const WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];

export const normaliseVin = (text: string) => text.replace(/[\s-]/g, "").toUpperCase();

/** Empty string = a valid VIN. */
export function vinProblem(vin: string): string {
  if (vin.length !== 17) return `A VIN has 17 characters (you typed ${vin.length}).`;
  if (/[IOQ]/.test(vin)) return "A VIN never contains the letters I, O or Q.";
  if (!/^[A-HJ-NPR-Z0-9]+$/.test(vin)) return "A VIN has only letters and numbers.";
  let total = 0;
  for (let i = 0; i < 17; i++) total += (/[0-9]/.test(vin[i]) ? Number(vin[i]) : VALUES[vin[i]]) * WEIGHTS[i];
  const digit = total % 11 === 10 ? "X" : String(total % 11);
  return vin[8] === digit ? "" : "This VIN does not add up. Check it for typos.";
}

/** Miles as typed ("48,200") → 48200; null when it is not a plain number. */
export function parseMiles(text: string): number | null {
  const t = text.trim();
  if (!/^\d{1,3}(,\d{3})*$|^\d+$/.test(t)) return null;
  return Number(t.replace(/,/g, ""));
}
