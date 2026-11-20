// Admin theme before the first paint, so a light-theme admin does not flash dark (src/admin/theme.tsx keeps it after).
// Loaded as a plain script from admin/index.html (hardening A8a: no inline script).
try {
  var t = localStorage.getItem("carlens-admin-theme");
  document.documentElement.dataset.theme = t === "light" || t === "dark" ? t
    : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
} catch (e) {}
