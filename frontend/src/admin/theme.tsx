// Light / dark theme for the admin app (owner, 12 Nov). The choice is kept in this browser only.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";
const KEY = "carlens-admin-theme";

function firstTheme(): Theme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({ theme: "dark", setTheme: () => {} });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(firstTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // Storage blocked: the theme still works for this visit.
    }
  }, [theme]);
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

export function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const option = (value: Theme, label: string, icon: ReactNode) => (
    <button role="radio" aria-checked={theme === value} aria-label={label} title={label} onClick={() => setTheme(value)}
      className={`grid h-7 w-7 place-items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent ${theme === value ? "bg-ink text-page" : "text-ink-3 hover:text-ink"}`}>
      {icon}
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Theme" className="flex gap-0.5 rounded-full bg-inset p-0.5">
      {option("light", "Light theme",
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>)}
      {option("dark", "Dark theme",
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>)}
    </div>
  );
}
