# Verification

Verified on 2026-11-23 using Windows, Docker Compose 2.23.3, PostgreSQL 17, Python 3.12 in the images, and local Microsoft Edge. All accounts, conversations and screenshots used synthetic data in temporary databases.

| Stage | Revision or scope | Result |
| --- | --- | --- |
| Original v1.1 before any edits | `c05c7eee5dc19bff227da7ffa8ea77508845b4b5` on `feat/fullstack-rebuild` | Production frontend and Docker image built. Alembic 0001 applied. Pytest 7 passed. Playwright 3 passed at 1440, 390 and 320 pixels. |
| Messenger first implementation | `fa33b04` | Compose readiness and frontend HTTP 200 confirmed. Two PostgreSQL integration tests passed, covering authentication, direct and group chat, search, history, WebSocket delivery and replay, and access controls. |
| AI data compatibility | Temporary database seeded at 0001 | Upgrade to 0002, downgrade to 0001, and re-upgrade retained the synthetic legacy message. |
| Dual-app deployment | Dedicated Compose project | Both services built and ran against their own healthy PostgreSQL instances. The final frontend lock files reported zero npm audit findings. Existing development containers and volumes were outside the test project. |
| Initial AI Chat release tests | PostgreSQL, HTTP/SSE, Provider transport, browser | Pytest 11 passed and Playwright 4 passed. Two duplicate mobile instances of the desktop workflow were skipped. Pytest covers baseline behavior, context, restoration, cross-user isolation, budget admission and the OpenAI request/stream contract. Playwright covers all three baseline viewports and a desktop edit, regeneration and recovery workflow. |
| Initial Messenger release tests | PostgreSQL, HTTP/WebSocket, browser | Pytest 2 passed and Playwright 1 passed. The API integration checks cover direct and group conversations and access controls. The browser test uses three separate accounts for live delivery, stable message order when a socket frame arrives late, and history after reload. |
| Messenger distributed acceptance | `04f8685` | Two independent API instances, Nginx balancing, WebSocket send in both directions, 20 concurrent writes, Redis outage and recovery, and API restart verified. [Measurements](messenger/acceptance.md) |
| AI Provider and history acceptance | `ac0d930` | 19 Pytest tests and 4 Playwright tests passed. Provider errors, reported and unavailable usage, cancellation, and schema upgrade/rollback were exercised. [Evidence](ai-chat/acceptance.md) |
| Final dual-app smoke | Isolated Compose project | Both applications became ready on their respective loopback ports, with distinct container networks and PostgreSQL volumes. |

The original v1.1 was the AI workspace baseline. The repository's original `main` contains the separate legacy React demo backed by ChatEngine.io. The current Messenger was built from scratch after confirming the original repository had no full-stack Messenger implementation.

The OpenAI request contract is tested with a controlled HTTP transport. A live provider smoke test requires operator-supplied credentials and a configured model. The existing Render services and demo URLs are outside this rollout.
