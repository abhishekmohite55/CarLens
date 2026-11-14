// Upload helpers for Home (stage F4). Limits always come from GET /api/config (CFG-4), never from here.

export type Limits = { allowed_types: string[]; max_size_mb: number; max_duration_sec: number };
export type RunRow = { run_id: string; file: string; status: string; failed_at: string | null; created_at: string };

/** Statuses that count as "a run in progress" (backend ACTIVE_STATUSES). */
export const ACTIVE = ["uploaded", "running", "awaiting_confirm"];

const MB = 1024 * 1024; // the backend counts max_size_mb in MiB

export function sizeText(bytes: number) {
  return `${Math.round(bytes / MB)} MB`;
}

export function durationText(seconds: number) {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Type and size, checked before any byte is sent (UP-3). Empty string = fine. */
export function checkFile(file: File, limits: Limits): string {
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
  if (!limits.allowed_types.includes(ext)) {
    const shown = ext ? `This is a .${ext} file.` : "This file has no type.";
    return `${shown} Use ${limits.allowed_types.join(", ")}.`;
  }
  if (file.size > limits.max_size_mb * MB) return `This video is ${sizeText(file.size)}. The limit is ${limits.max_size_mb} MB.`;
  return "";
}

export type UploadAnswer =
  | { kind: "run"; runId: string }
  | { kind: "same"; oldRunId: string; pendingId: string }
  | { kind: "refused"; status: number; code: string; message: string };

/** XMLHttpRequest, because fetch cannot report upload progress (UP-4). */
export function sendVideo(file: File, onProgress: (sent: number) => void): Promise<UploadAnswer> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/runs");
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      let data: Record<string, any> = {};
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        // not JSON: handled below as a refusal
      }
      if (xhr.status === 200 && data.run_id) return resolve({ kind: "run", runId: data.run_id });
      if (xhr.status === 409 && data.pending_id) return resolve({ kind: "same", oldRunId: data.duplicate_of, pendingId: data.pending_id });
      const error = data.error ?? data.detail?.error ?? {};
      resolve({ kind: "refused", status: xhr.status, code: error.code ?? "error",
        message: error.message ?? `Upload failed (${xhr.status}).` });
    };
    xhr.onerror = () => resolve({ kind: "refused", status: 0, code: "network",
      message: "Upload stopped because the connection dropped. Choose the video again to retry." });
    const form = new FormData();
    form.append("video", file);
    xhr.send(form);
  });
}
