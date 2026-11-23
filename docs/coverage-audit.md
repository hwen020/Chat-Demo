# ChatFlow technical coverage audit

**Implemented** means the code and the listed scenario have executable evidence. **Partial** means the narrower capability is verified and the stated gap remains. **Missing** means there is no implementation or measurement for the stated capability.

Paths below are relative to the repository root. Tests use synthetic accounts and disposable PostgreSQL instances. The original v1.1 remains at `c05c7ee`. The Messenger ordering repair is already in `9c226aa` and was exercised again on both viewport classes.

## Messenger

| Capability | Status | Code and test evidence |
| --- | --- | --- |
| React, TypeScript, FastAPI, SQLAlchemy, PostgreSQL, Alembic | Implemented | `apps/messenger/web/package.json`, `apps/messenger/api/app/db.py`, `apps/messenger/api/alembic/versions/0001_initial.py`. Image build, migration, and PostgreSQL integration suite. |
| Private and group chats; contact and conversation search | Implemented | `apps/messenger/api/app/main.py`. `apps/messenger/api/tests/test_messenger.py` and `apps/messenger/web/tests/messenger.spec.ts` exercise both chat types and filtering. |
| Message body search and cursor pagination | Implemented | `apps/messenger/api/app/main.py` applies a literal case-insensitive filter before the sequence cursor. `apps/messenger/web/src/main.tsx` exposes the filter without changing the live timeline. Tests cover more than one page, wildcard literals, membership denial, and desktop and mobile results. |
| WebSocket authentication, authorization, lifecycle and validation | Implemented | `apps/messenger/api/app/main.py` checks origin, cookie and membership on handshake, reads and sends. `test_messenger.py` checks revoked sessions, wrong origins and nonmember denial. `services/messenger/verify.py` checks different replicas, disconnect and restart. |
| Transactions, indexes, concurrency, order, deduplication and idempotency | Implemented | Chat row lock, sequence and sender request key in `apps/messenger/api/app/main.py` and `0001_initial.py`. The distributed harness compares 20 concurrent commits to both socket timelines; Playwright reorders and duplicates a real frame. |
| Redis Pub/Sub, post-commit recovery and cursor replay | Implemented | `apps/messenger/api/app/realtime.py` publishes after commit. Each socket pulls durable rows after its cursor at two-second intervals even with lost notifications. This is the compensation mechanism. `services/messenger/verify.py` stops Redis and one API, verifies committed delivery and verifies renewed subscriptions. Redis notifications themselves are ephemeral. |
| Nginx Upgrade, failover and load balancing | Implemented | `services/messenger/nginx.conf` and `docker-compose.yml`; the distributed harness verifies both instance IDs via the proxy, a WebSocket upgrade and the remaining instance during restart. |
| Rate limits, bounded input and account isolation | Implemented | `packages/shared/python/chatflow_shared/auth.py`, `apps/messenger/api/app/main.py`; PostgreSQL and browser fixtures verify member scope, request validation, and session revocation. |
| Structured logs, metrics and health checks | Implemented | `apps/messenger/api/app/main.py`, `realtime.py`, and `services/messenger/nginx.conf`. Redis fault logs are structured. Proxy access logs omit query strings, including message search terms. Per-instance counters cover sockets, subscription, notifications, publish errors and dropped queue items. Integration verifies the metrics endpoint and the distributed test confirms Nginx keeps it private. |
| Repeatable benchmark and load testing | Partial | `services/messenger/verify.py` measures 20 concurrent writes and 40 delivery samples with Redis/API fault injection. Sustained load, saturation curves and production latency targets remain unmeasured. |

## AI Chat

| Capability | Status | Code and test evidence |
| --- | --- | --- |
| React, TypeScript, FastAPI, SQLAlchemy, PostgreSQL, Alembic, SSE, Compose | Implemented | `apps/ai-chat/web/package.json`, `apps/ai-chat/api/app/db.py`, `apps/ai-chat/api/alembic/`, `docker-compose.yml`; Docker build, live PostgreSQL and browser tests. |
| OpenAI/Mock separation and server-side credentials | Partial | `apps/ai-chat/api/app/providers.py`, `model_config.py`, `worker.py`. `tests/test_openai.py` and `tests/test_upstream_worker.py` exercise real adapter behavior through a controlled HTTP transport and check the key is absent from SSE. Mock labeling is browser tested. A paid OpenAI request awaits server-side credentials. |
| SSE increments, cancellation, state persistence, partial output and replay | Implemented | `apps/ai-chat/api/app/main.py`, `worker.py`; `tests/test_api.py` checks cursor replay and expiry, `test_upstream_worker.py` checks delta persistence, terminal status and closing an open upstream stream. |
| Multi-turn context, context window, token and admission budgets | Implemented | `apps/ai-chat/api/app/model_config.py` and `main.py`. Tests cover ordered context, truncation, configured completion cap and PostgreSQL-backed per-user and global daily reservations. Input count is a conservative local estimate. |
| Upstream timeout, rate limit, error classification and retry | Implemented | `apps/ai-chat/api/app/providers.py` and `worker.py`. Transport tests cover 429, timeout, 401, 500 and interrupted streams. Browser validates user-initiated retry. Automatic retries are deferred because upstream cancellation or transport failure can leave a billable request. |
| Token Usage and cost statistics | Partial | `apps/ai-chat/api/app/worker.py` stores upstream-reported input/output counts. `main.py` and `web/src/main.tsx` expose reported versus unavailable usage; `model_config.py` persists estimated reservations. Verified real billing reconciliation and aggregate actual-cost reporting remain open. |
| Edit prompt, regenerate, delete and restore | Implemented | `apps/ai-chat/api/app/main.py`, `web/src/main.tsx`, `tests/test_api.py`, `web/tests/chat.spec.ts`. Database assertions cover the visible revision and restored history, with desktop browser coverage. |
| Existing history and reversible migrations | Implemented | `apps/ai-chat/api/alembic/versions/0002_ai_workspace.py`; `tests/test_legacy_migration.py` compares historic message identity, text and replay events through upgrade, downgrade and re-upgrade in an isolated schema. |
| Concurrent requests, logging, authorization and safe rendering | Implemented | `main.py` checks ownership; the migration defines one active generation per conversation. `test_api.py` covers concurrent idempotency and denied cross-user access. Worker logs omit prompts and secrets; browser checks Markdown HTML and image filtering. |
| Repeatable performance benchmark | Partial | `apps/ai-chat/api/tests/test_api.py` measures submission-to-first-delta and submission-to-completion on three controlled Mock generations. Run `python -m pytest -s -k context_edit_retry_delete_and_restore` against a disposable Mock deployment. Real-provider latency and sustained throughput remain unmeasured. |

## Both products

| Capability | Status | Code and test evidence |
| --- | --- | --- |
| Independent and simultaneous startup, database and permission isolation | Implemented | `docker-compose.yml` has distinct database volumes, networks and startup targets. Each app has its own session cookie, migrations, configuration and CI. Independent workflows and the joint Compose run verify startup. |
| CI workflows | Implemented | `.github/workflows/messenger.yml`, `.github/workflows/ci.yml` and `.github/workflows/security.yml` run product-specific and shared checks. |
| Dependency audit | Partial | `.github/workflows/security.yml` gates high-severity npm findings and Python advisories and publishes the Python reports. Full image and operating-system scanning is deferred. |
| Secret scanning | Implemented | `.github/workflows/security.yml` executes Gitleaks with redaction on the full reachable history. |
| Reproducible Docker builds | Partial | Both Dockerfiles use multistage builds and npm lock files. Direct Python packages are pinned; transitive package hashes and all build and Compose image digests are not locked. Images were rebuilt, but byte identity was not established. |
| Migration and recovery rehearsal | Implemented | The suite applies each migration and `services/verify-backup.sh` restores a fixture dump into a fresh database and compares the revision and message checksum. Production backup retention, off-site storage and recovery-time objectives were outside this rehearsal. |
| Documentation and desktop/mobile acceptance | Implemented | `README.md`, both app READMEs, `docs/messenger/architecture.md`, `docs/ai-chat/workspace.md`. Messenger validates desktop and 390px; AI validates desktop, 320px and 390px. |

## Audit run and reproduction

- Both npm lock files passed with zero reported advisories. The initial Python scan found seven Starlette advisories in each app. FastAPI 0.133.0 and Starlette 1.3.1 resolved those findings, and both reruns reported zero known vulnerabilities. [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/#01330-2026-02-24) and [Starlette release notes](https://starlette.dev/release-notes/#131-june-12-2026).
- The redacted Gitleaks scan found no leaks at `77eb75c`. Both application and security workflows passed on that commit, including patched dependency resolution and backup rehearsals. [Messenger](https://github.com/hwen020/Chat-Demo/actions/runs/45279814554) and [AI Chat](https://github.com/hwen020/Chat-Demo/actions/runs/45279814586) and [Security](https://github.com/hwen020/Chat-Demo/actions/runs/45279814607).
- The joint local run passed 3 Messenger Pytests and 2 Playwright viewports, plus the distributed fault harness. Its 20 writes produced 40 delivery observations, p95 209.2 ms, and the Redis outage sample arrived in 1022.4 ms. This is a bounded local workload.
- The same joint run passed 19 AI Pytests and 4 Playwright runs, with two duplicate mobile copies of the desktop-specific action test skipped.
- Backup restore compared message checksums and Alembic versions inside disposable PostgreSQL databases. The script expects existing synthetic message rows. To repeat, pipe `services/verify-backup.sh` to `docker compose -p YOUR_TEST_PROJECT exec -T messenger-db sh -s -- messenger` or to `docker compose -p YOUR_TEST_PROJECT exec -T db sh -s -- ai-chat`.

## Explicit missing capabilities

| Capability | Status | Evidence gap |
| --- | --- | --- |
| Automatic provider retries | Missing | The retry action is user initiated. No automatic retry policy exists for billable upstream operations. |
| Actual cost aggregation and billing reconciliation | Missing | Only provider token counts and estimated budget reservations are stored. |
| Container operating-system advisory scan | Missing | Current audit covers Python and npm packages plus Git history. |

## Maintenance boundaries

Keep the product workflows and databases independent. Re-run the fault harness and backup rehearsal after changes in delivery or persistence. Address Python advisories with focused version upgrades and regression tests. A real provider smoke test, billing reconciliation, sustained load, and bit-identical images remain separate follow-up work.

## Public demos

| Capability | Status | Evidence |
| --- | --- | --- |
| Two independently hosted products | Partial | [Blueprint](../render.yaml) and [cloud deployment guide](public-demo.md). Cloud account inventory and actual public URL acceptance await provider authorization. |
| Separate Render Static Sites | Missing | The prepared Render candidates serve the existing frontend and API on the same origin. Static-site cross-origin sessions and streams remain unverified. |
