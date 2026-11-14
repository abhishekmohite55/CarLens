import { LayoutGroup, MotionConfig } from "motion/react";
import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { HowItWorks, Questions } from "./Articles";
import { DoorForm, NotFound, Waiting } from "./Door";
import { OfflineLine, Reachable } from "./Problems";
import { Home } from "./Home";
import { Landing } from "./Landing";
import { RunPage } from "./RunPage";
import { homeFor, NeedStatus, SessionProvider, SignedOutOnly, useSession } from "./session";
import "./tester.css";

/** The landing page is for visitors; someone already signed in goes straight on. */
function Start({ children }: { children: ReactNode }) {
  const { me } = useSession();
  if (me) return <Navigate to={homeFor(me.status)} replace />;
  return children;
}

// Tester app (docs/frontend/12-frontend-plan.md, storyboard 13-storyboard.md): F1–F10.
// reducedMotion="user": with the device's reduced-motion setting, shapes change without moving.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <LayoutGroup>
        <BrowserRouter>
          <Reachable>
          <OfflineLine />
          <SessionProvider>
            <Routes>
              <Route path="/" element={<Start><Landing /></Start>} />
              <Route path="/sign-in" element={<SignedOutOnly><DoorForm mode="sign-in" /></SignedOutOnly>} />
              <Route path="/request-access" element={<SignedOutOnly><DoorForm mode="request" /></SignedOutOnly>} />
              <Route path="/waiting" element={<NeedStatus status="waiting"><Waiting /></NeedStatus>} />
              <Route path="/home" element={<NeedStatus status="approved"><Home /></NeedStatus>} />
              <Route path="/run/:id" element={<NeedStatus status="approved"><RunPage /></NeedStatus>} />
              <Route path="/how-it-works" element={<HowItWorks />} />
              <Route path="/questions" element={<Questions />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </SessionProvider>
          </Reachable>
        </BrowserRouter>
      </LayoutGroup>
    </MotionConfig>
  </StrictMode>,
);
