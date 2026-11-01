# CarLens — Setup and Run (Windows)

## Prerequisites

- Python 3.12 (`py -3.12 --version` to confirm)
- Node 20+ (for the frontend, Stage 2+)
- `.env` in `F:\CarLens\` with keys: `GEMINI_API_KEY`, `TAVILY_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`

## Backend setup (once)

```
cd F:\CarLens\backend
"C:\Users\abhis\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Start the backend

```
cd F:\CarLens\backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000/inspector** — the dev inspector page.

## Check external APIs

```
cd F:\CarLens\backend
.venv\Scripts\activate
python -m scripts.check_apis
```

Results are saved to `runs/_checks/<timestamp>.json`.

## Endpoints (Stage 1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Upload limits and node list |
| POST | `/api/runs` | Upload a video (multipart, field `video`) |
| GET | `/api/runs/{run_id}` | Run snapshot |
| GET | `/api/runs/{run_id}/events` | SSE stream (full replay on reconnect) |
| GET | `/api/runs/{run_id}/files/{path}` | Files inside the run folder |
| GET | `/inspector` | Dev inspector page |

## Config

- **Limits and model names:** edit `config.yaml` at the project root. Changes apply on the next request — no restart needed.
- **Secrets:** `.env` at the project root. Restart uvicorn after editing secrets.

## Notes

- `runs/` and `.env` are never committed (see `.gitignore`).
- The venv is at `backend/.venv/` — not committed.
- Python 3.12.10 (`C:\Users\abhis\AppData\Local\Programs\Python\Python312\python.exe`).
