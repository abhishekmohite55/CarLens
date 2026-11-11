# CarLens

Upload a walkaround video of a used car and get a supported price range in INR. An AI pipeline finds the car's details, damage and tyre condition, searches the web for prices, and Python works out the price. Every step shows what was sent to each AI call and what came back.

## How it works

```
upload -> locate -> frames -> verify -> confirm -> photos -> plan -> search -> extract -> pricing
```

| Step | What it does |
|---|---|
| locate | Gemini watches the video and lists where the plate, badge, odometer, tyres and damage appear |
| frames | OpenCV keeps the sharpest frame for each item |
| verify | An AI model checks each frame: damage, tyre condition, plate, km, make/model/year |
| confirm | You check the car details (pre-filled) and can add tyre or odometer photos |
| photos | Reads the extra photos, if any |
| plan | Builds web search queries for listings, new-car price and repairs |
| search | Runs the queries on Tavily |
| extract | An AI model copies prices out of the search results; Python checks each one |
| pricing | Python: new price, yearly depreciation from listings, minus repairs, gives the range |

Each run is saved in `runs/<run_id>/`, one folder per step. If a step fails, the run stops there and can be resumed from that step.

## Setup (Windows, once)

You need Python 3.12 and a `.env` file in the project root: copy `.env.example` to `.env` and fill in every value.

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 2
```

Open **http://localhost:8000/inspector**, upload a video and follow the steps.
`--timeout-graceful-shutdown 2` lets Ctrl+C stop the server while the inspector page is open.

## Dev database

Needs Docker Desktop. Postgres and pgAdmin run in containers; the backend in its venv connects to Postgres.

```
docker compose up -d postgres pgadmin   # start (daily work)
docker compose stop       # stop, keep data
```

pgAdmin: **http://localhost:5050** (login `PGADMIN_EMAIL` / `PGADMIN_PASSWORD`). Add a server with host `postgres`, port `5432`, user `carlens`.
`docker compose down -v` deletes all database data.

Tables are created by Alembic migrations (`backend/alembic/versions/`). After `docker compose up -d`, from `backend` with the venv active:

```
alembic upgrade head
```

Tests use a separate database `carlens_test` (`TEST_DATABASE_URL` in `.env`), created once with
`docker compose exec postgres createdb -U carlens carlens_test`.

## Backend in Docker

The same image AWS will run. `config.yaml`, `prompts/` and `runs/` are mounted from this folder; `.env` is passed as environment variables. On start the container runs `alembic upgrade head`, then the server. Stop the venv server first: both use port 8000.

```
docker compose build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) backend
docker compose up -d
docker compose logs -f backend
docker compose down
```

Open **http://127.0.0.1:8000/inspector**. Rebuild after a code or `requirements.txt` change.

## Tests

```
cd backend
.venv\Scripts\activate
python -m pytest -q
```

## Frontend (tester app + admin app)

`frontend/` is one React + Vite + TypeScript + Tailwind project with two apps: the tester app at `/` (built in the frontend chat) and the admin app at `/admin/`. Needs Node.js 20 or newer. The backend must be running on port 8000 (container or venv).

```
cd frontend
npm install        # first time, and after package.json changes
npm run dev        # http://127.0.0.1:5173/admin/
npm run build      # type check + production build into frontend/dist
```

## CI

Every push to GitHub runs `.github/workflows/ci.yml`: **lint** (ruff, pyflakes rules), **test** (`pytest` against a throwaway Postgres 17) and **image** (`docker build` of the backend). `main` only accepts a pull request whose 3 checks are green.

Same lint on the laptop (venv active, from the project root):

```
pip install ruff==0.17.4
ruff check --select F backend
```

Merging a stage: push the branch, open a pull request into `main` on GitHub, merge it when the checks are green, then `git checkout main` and `git pull`.

## Config

- `config.yaml` (project root): models, limits and pricing settings. Changes apply without a restart.
- `.env`: API keys only. Restart the server after changing it.
- `runs/` and `.env` are never committed.
