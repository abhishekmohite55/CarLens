import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import "../index.css";
import { AdminApp } from "./AdminApp";
import { ThemeProvider } from "./theme";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/admin">
      <ThemeProvider>
        <AdminApp />
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
);
