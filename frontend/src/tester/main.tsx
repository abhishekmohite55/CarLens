import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";

// Tester app: built in the frontend chat on this project (docs/platform/06-admin.md §7).
// Until then, testers use the backend's /login page.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 text-neutral-300">
      <p>CarLens is coming soon.</p>
    </div>
  </StrictMode>,
);
