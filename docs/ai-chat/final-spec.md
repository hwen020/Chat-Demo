# ChatFlow release candidate specification

## Source reconciliation

| Topic | Chat-Demo reference | Chatbot audit | ChatFlow decision |
| --- | --- | --- | --- |
| Product | Direct and group messaging | AI conversation MVP | Independent AI chat with one owner per conversation |
| Repository | In-place work and historical branch | Standalone original project | Continue the independent chatflow-ai-platform checkout; preserve legacy projects and history as-is |
| Transport | Socket.IO, room membership and ACK | REST and SSE | REST commits a generation; a separate authenticated SSE subscription replays persisted events |
| Backend | Express, Prisma, PostgreSQL | FastAPI, SQLAlchemy, Alembic, PostgreSQL | FastAPI stack, migrations and database-enforced idempotency |
| UI | Three panes, settings, collaboration controls | Original conversation UI | Original responsive two-pane workspace, direct links and mobile drawer; verify 1440, 390 and 320 px |
| Release | Public demo and deployment | Public Mock demo possible | Local release candidate with deployment instructions and CI config; external release depends on explicit approval |

## First-release behavior

Use deterministic Mock output with a server-side provider interface. Support email registration, login, revocable sessions, conversation creation/renaming/deletion, paged message history, persistent output and explicit owner-only cancellation. Secure cookies are the default for HTTPS; loopback testing opts into HTTP explicitly. Apply Origin checks to writes, hash passwords and session tokens, scope all resources to the owner, and avoid logging message content or secrets.

A message submission atomically reserves the generation with a request key. Retrying the same content returns that generation; reusing the key for different content returns 409. The worker persists sequenced SSE events, and subscribers resume by event cursor for 15 minutes after completion. Timeouts and explicit cancellation leave a durable terminal state; a lost browser connection leaves the job running, which permits replay. When the window has expired, reload saved history. The Mock provider is bounded; a future real provider must add a bounded network timeout and cancellation-aware connection teardown.

No group chat, attachments, presence, receipts, ChatEngine integration, old assets, or real model requests are part of this release. A single application process and PostgreSQL keep the local setup reproducible. Docker Compose, Pytest and Playwright define the release checks; see the local test report for results and limits.
