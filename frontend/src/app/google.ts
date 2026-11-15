// Google sign-in (Google Identity Services). The client ID comes from GET /api/auth/google-client-id (public).
// Google allows plain http only on localhost / 127.0.0.1; on the laptop's Wi-Fi address the button will not work.

type GoogleId = {
  initialize: (options: { client_id: string; callback: (answer: { credential: string }) => void }) => void;
  renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
};
declare global {
  interface Window { google?: { accounts: { id: GoogleId } } }
}

let ready: Promise<GoogleId | null> | null = null;

/** Loads Google's script once; null when Google sign-in is not set up or cannot load. */
export function loadGoogle(): Promise<GoogleId | null> {
  ready ??= (async () => {
    const answer = await fetch("/api/auth/google-client-id").then((r) => r.json()).catch(() => ({}));
    const clientId: string = answer.client_id ?? "";
    if (!clientId) return null;
    await new Promise<void>((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.onload = () => resolve();
      script.onerror = () => reject();
      document.head.appendChild(script);
    }).catch(() => null);
    const id = window.google?.accounts.id;
    if (!id) return null;
    id.initialize({ client_id: clientId, callback: (a) => onCredential(a.credential) });
    return id;
  })();
  return ready;
}

// The page currently showing the button decides what happens with Google's answer.
let onCredential: (credential: string) => void = () => {};
export function setGoogleHandler(handler: (credential: string) => void) {
  onCredential = handler;
}
