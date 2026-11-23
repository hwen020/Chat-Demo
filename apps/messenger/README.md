# ChatFlow Messenger

## Public demo

Messenger has a separate prepared Render Free deployment. Public URLs are pending account access. A first visit can take about one minute while a Free instance wakes. See [deployment and public acceptance](../../docs/public-demo.md).

A real-time messaging application for direct and group conversations. React and TypeScript provide a contact and conversation workspace. FastAPI serves REST and authenticated WebSocket connections. PostgreSQL stores accounts, memberships, messages and sessions. Nginx balances two API instances and upgrades WebSockets. Redis Pub/Sub wakes the other instance after a message commits.

## Quick start

From the repository root, run `docker compose up --build messenger` and open [Messenger](http://127.0.0.1:8081). Register two synthetic accounts in separate browser profiles, then start a chat with the other account's email. For a group conversation, enter multiple registered email addresses and a group name. Use **Find messages** inside a chat to search its message text. Earlier matches use the same sequence cursor as history.

Set the Compose values listed in [.env.example](.env.example) through the shell, a root `.env` file or `docker compose --env-file apps/messenger/.env …`. Compose keeps PostgreSQL private and uses the dedicated `chatflow_messenger_database` volume. `docker compose stop messenger messenger-api-a messenger-api-b messenger-redis messenger-db` stops the Messenger stack.

## Native development and tests

Use Python 3.12, Node.js 22 and a dedicated PostgreSQL 17 database. Set `DATABASE_URL`, `APP_ORIGINS=http://127.0.0.1:5174`, `COOKIE_SECURE=0`, and `PYTHONPATH` to the absolute path to `packages/shared/python`.

In `apps/messenger/api`:

```sh
python -m pip install -r requirements-test.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

In `apps/messenger/web`, run `npm ci` and `npm run dev -- --host 127.0.0.1`. Vite proxies REST and WebSocket traffic. Set `MESSENGER_REDIS_URL` to enable Redis in a native instance. The standalone development process can serve its own WebSockets. `npm run build` builds the static frontend. Set `STATIC_DIR` to the absolute `web/dist` path to serve the built frontend with FastAPI.

For the integration suite, use a fresh test database, set `COOKIE_SECURE=0` and `APP_ORIGINS=http://127.0.0.1:5173`, migrate it, then run `python -m pytest -q` from `api/`. Tests cover registration and login, session revocation, direct and group chat, search, persistence, socket delivery and replay, and access checks.

For the two-browser-session workflow, start an isolated Messenger instance, set `MESSENGER_WEB` to its URL, and run `npx playwright install chromium` and `npm test` from `web/`. The browser test registers synthetic accounts and checks direct and group delivery.

## Version and test evidence

The API pins FastAPI 0.133.0 and Starlette 1.3.1 in [requirements.txt](api/requirements.txt). The shared security workflow scans npm and Python dependencies plus reachable Git history. Messenger's browser suite runs the delayed and duplicated WebSocket frame regression and message search on desktop and at 390px. See the [coverage matrix](../../docs/coverage-audit.md).

## Distributed acceptance

From the repository root, use a dedicated temporary project and free loopback ports. Install the API test requirements with Python 3.12, and run:

```sh
export MESSENGER_PORT=18081
export MESSENGER_WEB=http://127.0.0.1:18081
docker compose -p chatflow-messenger-check -f docker-compose.yml -f services/messenger/test.compose.yml up --build -d messenger
python services/messenger/verify.py chatflow-messenger-check
docker compose -p chatflow-messenger-check -f docker-compose.yml -f services/messenger/test.compose.yml down -v
```

The override publishes test-only API ports 18091 and 18092, configurable through `MESSENGER_TEST_PORT_A` and `MESSENGER_TEST_PORT_B`. The test confirms proxy balancing, opens sockets on different instances, sends concurrent messages, disconnects Redis, restarts an API, and verifies PostgreSQL cursor replay. `down -v` removes the temporary test project and its volumes. Run the browser suite against the same Nginx URL before cleanup. See [acceptance evidence](../../docs/messenger/acceptance.md).

## Deploy

From the repository root, build with `docker build -f apps/messenger/Dockerfile -t chatflow-messenger .`. Provide Messenger-only PostgreSQL and Redis services. Set `DATABASE_URL`, `MESSENGER_REDIS_URL` and the exact HTTPS `APP_ORIGINS` on both replicas. Assign distinct `MESSENGER_INSTANCE` names and keep `COOKIE_SECURE=1`. Run `alembic upgrade head` once before starting the replicas. Configure the Nginx upstream addresses and terminate TLS at the deployment ingress. Forward HTTP and WebSocket upgrades to API port 8000. Check `/healthz` and `/readyz`. Scrape `/metrics` on each private API instance for socket and Redis signal counters. Nginx blocks this route on the public listener. See [architecture](../../docs/messenger/architecture.md).
