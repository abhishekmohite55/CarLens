#!/bin/sh
# Container start: apply new migrations (applied ones are skipped), then run the server.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 2
