# ChatFlow handoff

## Checkout

- Repository: https://github.com/hwen020/Chat-Demo
- Branch: feat/fullstack-rebuild
- Validated implementation commit: e27e28cdd696e172c4d4fd99bd250462ce70db1f
- The branch tip also includes this handoff commit. In a checkout, git rev-parse HEAD prints the exact current SHA.

On a fresh computer with Git, Docker Engine or Desktop, and the Compose plugin:

    git clone --branch feat/fullstack-rebuild https://github.com/hwen020/Chat-Demo.git chatflow
    cd chatflow
    git rev-parse HEAD
    docker compose up --build

Open http://127.0.0.1:8080 and register a synthetic account. Explore the API at http://127.0.0.1:8080/docs. Docker Compose makes an isolated PostgreSQL database and runs Alembic before serving. No database, node_modules, or credentials need to be copied. Stop with docker compose down; the named volume retains local data.

## Native development and configuration

- Install Python and Node, create a Python virtual environment, then run python -m pip install -r api/requirements-test.txt. In web/, run npm ci and npm run build.
- With a local PostgreSQL server, create an isolated chatflow database and user. Set DATABASE_URL to a value such as postgresql+psycopg://chatflow:LOCAL_PASSWORD@127.0.0.1:55432/chatflow, using local-only credentials. From api/, run alembic upgrade head, then uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log.
- STATIC_DIR points to the absolute web/dist directory. APP_ORIGINS should match the browser origin, for example http://127.0.0.1:8000. COOKIE_SECURE=0 is for loopback HTTP only. Leave secure cookies enabled for HTTPS. CHATFLOW_DB_PASSWORD optionally overrides the local Compose database password.
- For API tests set CHATFLOW_TEST_BASE and CHATFLOW_TEST_ORIGIN to the local API URL and run python -m pytest -q from api/. Use a dedicated test database because a test modifies an event expiry. For browser tests set CHATFLOW_WEB, run npx playwright install chromium and npm test from web/.

## Current behavior and verification

Original React/TypeScript UI, FastAPI/PostgreSQL, account registration and revocable sessions, owner-scoped conversations and history, deterministic Mock replies, idempotent submission, SSE replay, cancellation and timeout. No real model key is required.

Release worktree verification: Alembic 0001 on fresh PostgreSQL passed, 7 Pytest tests passed, TypeScript/Vite build passed, and 3 Playwright tests passed at 1440, 390 and 320 px. Docker engine was unavailable on the verification machine, so local container startup was not tested. See test-report.md for specifics. GitHub Actions results are per commit and should be checked on the repository Actions page.

Follow-up: validate container startup in Docker, confirm the branch CI run, and only then consider a real model adapter and server-side usage limits. Replay is available for 15 minutes after completion; after expiry the UI reads saved history. The model remains Mock, and production hosting is out of scope.
