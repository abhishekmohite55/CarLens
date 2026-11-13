// Light / dark theme for the tester app. The first value is set before first paint by the script in index.html
// (saved choice, else the device setting); the choice is kept in this browser only.
import { useState } from "react";

type Theme = "light" | "dark";
const KEY = "carlens-theme";

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"));
  const flip = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Storage blocked: the theme still works for this visit.
    }
    setTheme(next);
  };
  return (
    <button onClick={flip} className="text-label rounded-full border border-line-strong px-4 py-2 text-ink-2 hover:text-ink">
      {theme === "dark" ? "Light theme" : "Dark theme"}
    </button>
  );
}
