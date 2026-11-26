#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 --no-access-log --ws-max-size 32768
