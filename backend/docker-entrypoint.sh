#!/bin/sh
# Container start: migrate the database and add new config settings (app/startup.py, step 9.3), then the server.
# The server always starts: a database newer than the code, or a failed migration, is reported by health instead.
python -m app.startup
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 2
