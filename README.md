# ChatFlow

ChatFlow is an original, local-first conversation workspace. A deterministic Mock model streams replies while PostgreSQL stores accounts, conversations, messages, and replayable events. ChatFlow makes no external model requests in this release.

## Run locally

Prerequisites are Docker Engine and the Docker Compose plugin. From this project directory:

```sh
docker compose up --build
```

Open http://127.0.0.1:8080. Register with a test email, create a conversation and send a message. Open a second browser profile to try another account. API docs are at http://127.0.0.1:8080/docs.

Search conversation titles in the sidebar or mobile drawer. The filter is case-insensitive and covers the latest 100 conversations returned by the history API.

Compose binds the app to loopback and keeps PostgreSQL on the Compose network. It creates a named volume and applies Alembic on startup. Use `docker compose down` to stop it while retaining local data. The database password in the Compose example is for local development. The example file lists the optional override.

### Run against a local PostgreSQL instance

Create a dedicated database and set `DATABASE_URL` to its SQLAlchemy URL. Install `api/requirements-test.txt`. In `web/` run `npm ci` and `npm run build`. Set `STATIC_DIR` to the absolute path to `web/dist`. For loopback HTTP only, set `COOKIE_SECURE=0`. Set `APP_ORIGINS` to exactly the URL used in the browser, for example `http://127.0.0.1:8000`.

From `api/`, run `alembic upgrade head` then `uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log`. To use development HMR, run `npm run dev` from `web/` and include that origin in `APP_ORIGINS`.

## Verify

With a dedicated running server/database, set `CHATFLOW_TEST_ORIGIN` to an allowed origin and `CHATFLOW_TEST_BASE` to the API base URL. From `api/`, run `python -m pytest -q`. One test explicitly expires replay in the test database. From `web/`, install Chromium with `npx playwright install chromium`, set `CHATFLOW_WEB` to the frontend URL and run `npm test`. Tests exercise desktop and 390px and 320px viewports. GitHub Actions builds the app, applies migrations, and runs both suites on PostgreSQL.

CI uses Ubuntu 24.04 for the locked Playwright version. Dependency installation, the frontend build, and Chromium setup are reported as separate steps.

See [final technical specification](docs/final-spec.md), [architecture](docs/architecture.md), [API](docs/api.md) and [local test report](docs/test-report.md).

## Deployment configuration

Use HTTPS, secure cookies (default), an explicit HTTPS origin, a separate Postgres database and deployment-managed secrets. Run `alembic upgrade head` ahead of starting the service. Health probes use `/healthz` and `/readyz`. Keep reverse-proxy SSE buffering disabled and set its idle timeout above the 10-second heartbeat. Keep the initial instance size and rate limits suited to a personal demo. The app stores conversation text and account emails in PostgreSQL. Supply only sample content on a public demo and define a database retention procedure before enabling public registrations.

The worker uses the Mock provider. A real model can later implement the provider protocol with server-managed credentials and hard time and usage limits. This repository contains original UI and code and uses no files from the older SideProject applications.
