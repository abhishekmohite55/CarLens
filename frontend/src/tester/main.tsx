import { LayoutGroup, MotionConfig } from "motion/react";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { DoorForm, NotFound, Waiting } from "./Door";
import { Home } from "./Home";
import { Landing } from "./Landing";
import { RunPage } from "./RunPage";
import { homeFor, NeedStatus, SessionProvider, SignedOutOnly, useSession } from "./session";
import { TestPage } from "./TestPage";
import "./tester.css";

/** The landing page is for visitors; someone already signed in goes straight on. */
function Start({ children }: { children: ReactNode }) {
  const { me } = useSession();
  if (me) return <Navigate to={homeFor(me.status)} replace />;
  return children;
}

// Tester app (docs/frontend/12-frontend-plan.md). F5: run page part 1 (locate, frames, plate, verify); confirm arrives in F6.
// F1's test page stays at /look for checking the look.
// reducedMotion="user": with the device's reduced-motion setting, shapes change without moving.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <LayoutGroup>
        <BrowserRouter>
          <SessionProvider>
            <Routes>
              <Route path="/" element={<Start><Landing /></Start>} />
              <Route path="/sign-in" element={<SignedOutOnly><DoorForm mode="sign-in" /></SignedOutOnly>} />
              <Route path="/request-access" element={<SignedOutOnly><DoorForm mode="request" /></SignedOutOnly>} />
              <Route path="/waiting" element={<NeedStatus status="waiting"><Waiting /></NeedStatus>} />
              <Route path="/home" element={<NeedStatus status="approved"><Home /></NeedStatus>} />
              <Route path="/run/:id" element={<NeedStatus status="approved"><RunPage /></NeedStatus>} />
              <Route path="/look" element={<TestPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </SessionProvider>
        </BrowserRouter>
      </LayoutGroup>
    </MotionConfig>
  </StrictMode>,
);
