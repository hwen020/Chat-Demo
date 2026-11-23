# ChatFlow Messenger

A real-time messaging application for direct and group conversations. React and TypeScript provide a contact and conversation workspace. FastAPI serves REST and authenticated WebSocket connections. PostgreSQL stores accounts, memberships, messages and sessions.

## Quick start

From the repository root, run `docker compose up --build messenger` and open [Messenger](http://127.0.0.1:8081). Register two synthetic accounts in separate browser profiles, then start a chat with the other account's email. For a group conversation, enter multiple registered email addresses and a group name.

Set the Compose values listed in [.env.example](.env.example) through the shell, a root `.env` file or `docker compose --env-file apps/messenger/.env …`. Compose keeps PostgreSQL private and uses the dedicated `chatflow_messenger_database` volume. `docker compose stop messenger messenger-db` stops only Messenger.

## Native development and tests

Use Python 3.12, Node.js 22 and a dedicated PostgreSQL 17 database. Set `DATABASE_URL`, `APP_ORIGINS=http://127.0.0.1:5174`, `COOKIE_SECURE=0`, and `PYTHONPATH` to the absolute path to `packages/shared/python`.

In `apps/messenger/api`:

```sh
python -m pip install -r requirements-test.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

In `apps/messenger/web`, run `npm ci` and `npm run dev -- --host 127.0.0.1`. Vite proxies REST and WebSocket traffic. `npm run build` builds the static frontend. Set `STATIC_DIR` to the absolute `web/dist` path to serve the built frontend with FastAPI.

For the integration suite, use a fresh test database, set `COOKIE_SECURE=0` and `APP_ORIGINS=http://127.0.0.1:5173`, migrate it, then run `python -m pytest -q` from `api/`. Tests cover registration and login, session revocation, direct and group chat, search, persistence, socket delivery and replay, and access checks.

## Deploy

From the repository root, build with `docker build -f apps/messenger/Dockerfile -t chatflow-messenger .`. Provision a dedicated database, set `DATABASE_URL` and the exact HTTPS `APP_ORIGINS`, keep `COOKIE_SECURE=1`, and run `alembic upgrade head` before starting the container. Route HTTP and WebSocket upgrades to the container port 8000. Check `/healthz` and `/readyz`. See [architecture](../../docs/messenger/architecture.md).
