// CarLens frontend (platform step 6, docs/platform/06-admin.md §7): one project, two apps.
//   /        tester app (index.html)       built in the frontend chat
//   /admin/  admin app  (admin/index.html) built in step 6
// In development, /api goes to the backend on :8000 (container or venv), so pages and API share one address
// and the sign-in cookie works as it will behind nginx.
import { resolve } from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Connect } from "vite";

// /admin, /admin/users, ... (no file extension) → the admin page; the admin app's router takes it from there.
const adminFallback: Connect.NextHandleFunction = (req, _res, next) => {
  const path = (req.url ?? "").split("?")[0];
  if (/^\/admin(\/[^.]*)?$/.test(path)) req.url = "/admin/index.html";
  next();
};

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "admin-page-fallback",
      configureServer: (server) => void server.middlewares.use(adminFallback),
      configurePreviewServer: (server) => void server.middlewares.use(adminFallback),
    },
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    rollupOptions: {
      input: {
        tester: resolve(import.meta.dirname, "index.html"),
        admin: resolve(import.meta.dirname, "admin/index.html"),
      },
    },
  },
});
