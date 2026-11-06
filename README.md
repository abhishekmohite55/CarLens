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

You need Python 3.12 and a `.env` file in the project root with `GEMINI_API_KEY`, `TAVILY_API_KEY`, `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_HOST`.

```
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install --no-deps rapidocr==3.10.0
```

`--no-deps` keeps the project's `opencv-python` (rapidocr would pull in a conflicting OpenCV).

## Run

```
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 2
```

Open **http://localhost:8000/inspector**, upload a video and follow the steps.
`--timeout-graceful-shutdown 2` lets Ctrl+C stop the server while the inspector page is open.

## Tests

```
cd backend
.venv\Scripts\activate
python -m pytest -q
```

## Config

- `config.yaml` (project root): models, limits and pricing settings. Changes apply without a restart.
- `.env`: API keys only. Restart the server after changing it.
- `runs/` and `.env` are never committed.
