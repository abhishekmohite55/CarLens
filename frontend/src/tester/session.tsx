// Who is signed in, shared by every screen of the tester app (uses the shared useMe hook, like the admin app).
import { createContext, useContext, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useMe } from "../shared/useMe";

type Session = ReturnType<typeof useMe>;
const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  return <SessionContext.Provider value={useMe()}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext)!;

/** Where a signed-in person belongs: approved (or admin) → Home, pending / rejected → the waiting screen. */
export function homeFor(status: string | undefined) {
  return status === "approved" ? "/home" : "/waiting";
}

/** Where to go after signing in: back to the page that needed it (?next=/run/…), else Home or the waiting screen. */
export function afterSignIn(status: string | undefined, search: string) {
  const next = new URLSearchParams(search).get("next");
  return status === "approved" && next?.startsWith("/") && !next.startsWith("//") ? next : homeFor(status);
}

/** Screens for signed-out visitors: a signed-in person is sent on. */
export function SignedOutOnly({ children }: { children: ReactNode }) {
  const { me } = useSession();
  const { search } = useLocation();
  if (me) return <Navigate to={afterSignIn(me.status, search)} replace />;
  return children;
}

/** Screens that need someone signed in with this status. undefined = still asking the server. */
export function NeedStatus({ status, children }: { status: "approved" | "waiting"; children: ReactNode }) {
  const { me } = useSession();
  if (me === undefined) return null;
  if (me === null) return <Navigate to="/sign-in" replace />;
  const isApproved = me.status === "approved";
  if ((status === "approved") !== isApproved) return <Navigate to={homeFor(me.status)} replace />;
  return children;
}
