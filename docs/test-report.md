# ChatFlow local RC acceptance report

Date: 2026-11-22. Environment: Windows, Python 3.9.7, Node 18.17, PostgreSQL 17.5 with an isolated chatflow_rc database, and local Edge. The built frontend and REST/SSE API ran together over loopback. The model was deterministic Mock throughout.

| Stage | Files | Status and observed results | Open items / handoff |
| --- | --- | --- | --- |
| 1. Scope and schema | docs/final-spec.md, api/alembic/ | PASS. Fresh RC database migrated to Alembic 0001 head. Mock unit test passed independently in 0.02 s. | Continue through the live API. No schema change was needed for cancellation. |
| 2. Backend | api/app/main.py, api/app/worker.py, api/tests/test_api.py | PASS. 7 Pytest tests passed in 7.34 s against PostgreSQL and real HTTP. Cases include cookie auth/revocation, Origin checks, cross-user isolation, conversation CRUD, concurrent idempotency, actual disconnect and cursor replay, expired replay fallback, rate limits, owner-only cancellation and the running generation deadline. | Real model integration intentionally outside scope. Proceed with browser validation on the same build. |
| 3. Frontend | web/src/main.tsx, web/playwright.config.ts, web/tests/chat.spec.ts | PASS. TypeScript plus Vite production build succeeded. 3 Playwright tests passed in 22.2 s (1440, 390 and 320 pixels). Each completed a Mock conversation, recovered from an interrupted first SSE subscription, reopened the direct conversation URL, checked the saved reply and verified no horizontal page overflow. | Existing browser E2E covers reconnect and the primary chat workflow; explicit cancel and timeout were exercised at the API level. |
| 4. Delivery | README.md, docs/api.md, docs/architecture.md, Dockerfile, compose.yaml, .github/workflows/ci.yml | NOT TESTED for a container launch and remote CI. Compose/CI configs were preserved from the existing app; local integration exercised PostgreSQL and the built web assets directly. | Docker executable is unavailable on this host. No push, remote CI run or public deployment was performed. |

The Pytest run produced a JUnit report in the local temporary directory. Playwright saved the three browser captures under its local test-results directory.

## Release branch verification

Rebuilt from the clean dependency lock in the Chat-Demo release worktree. A fresh PostgreSQL database migrated to 0001. Pytest: 7 passed (5.11 s). TypeScript and Vite build: passed. Playwright: 3 passed (20.9 s), covering 1440, 390 and 320 px. Docker engine unavailable, so container startup remains untested locally.
