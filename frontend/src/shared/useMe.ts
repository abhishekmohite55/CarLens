import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Me } from "./api";

/** Who is signed in: undefined while loading, null when signed out. problem: the backend could not answer (step 9.3:
 * e.g. its database is down), so the page can say so instead of staying blank. */
export function useMe() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [problem, setProblem] = useState("");

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/auth/me"));
      setProblem("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        setProblem("");
      } else {
        setProblem(e instanceof Error ? e.message : "The backend did not answer.");
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setMe(null);
  }, []);

  return { me, setMe, refresh, signOut, problem };
}
