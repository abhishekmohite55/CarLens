// App theme before the first paint: the saved choice, else the device setting (src/app/theme.tsx keeps it after).
// Loaded as a plain script from index.html (hardening A8a: no inline script).
try {
  var t = localStorage.getItem("carlens-theme");
  document.documentElement.dataset.theme = t === "light" || t === "dark" ? t
    : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
} catch (e) {}
