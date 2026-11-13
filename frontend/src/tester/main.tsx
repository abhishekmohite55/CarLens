import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { Door } from "./Door";
import { Landing } from "./Landing";
import { TestPage } from "./TestPage";
import "./tester.css";

// Tester app (docs/frontend/12-frontend-plan.md). F2: landing page; F1's test page stays at /look for checking the look.
// reducedMotion="user": with the device's reduced-motion setting, shapes change without moving.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/sign-in" element={<Door title="Sign in" />} />
          <Route path="/request-access" element={<Door title="Request access" />} />
          <Route path="/look" element={<TestPage />} />
          <Route path="*" element={<Door title="This page does not exist." text="Check the address, or go back to the start." />} />
        </Routes>
      </BrowserRouter>
    </MotionConfig>
  </StrictMode>,
);
