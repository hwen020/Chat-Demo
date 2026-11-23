# AI Chat acceptance

- Implementation commit `ac0d930756d277adab29dca6cbee60c79e674c92`. Original v1.1 baseline `c05c7eee5dc19bff227da7ffa8ea77508845b4b5`. [AI implementation on GitHub](https://github.com/hwen020/Chat-Demo/commit/ac0d930756d277adab29dca6cbee60c79e674c92)
- Stack, design decisions, architecture diagram and three English résumé descriptions. [AI Chat architecture](workspace.md)
- Deployment configuration and optional server-side real-mode setup. [AI Chat README](../../apps/ai-chat/README.md)
- Independent GitHub workflow and artifacts. [AI Chat CI](https://github.com/hwen020/Chat-Demo/actions/workflows/ci.yml)

## Security patch and coverage follow-up

Commit `77eb75c` pins FastAPI 0.133.0 and Starlette 1.3.1. The patched suite passed 19 backend tests and 4 browser cases, with two redundant mobile copies of the desktop action test skipped. CI recorded 164.1 to 314.6 ms to the first delta across three Mock SSE samples and restored revision 0002 with a matching synthetic message checksum. The OpenAI adapter is tested with an HTTP fixture. The CI browser passes use Mock and live OpenAI remains unverified. [AI Chat CI](https://github.com/hwen020/Chat-Demo/actions/runs/45279814586) ? [Security audit](https://github.com/hwen020/Chat-Demo/actions/runs/45279814607)

## Original local acceptance on 2026-11-23

The production build and isolated PostgreSQL Compose startup passed. The baseline v1.1 first passed 7 API tests and 3 browser tests before migration.

| Coverage | Evidence |
| --- | --- |
| History preservation | A test created revision 0001 in a disposable PostgreSQL schema, inserted a completed conversation and its replay event, upgraded to 0002, downgraded, and upgraded again. Original message IDs, text and replay rows survived. |
| OpenAI request boundary | The real adapter was exercised with a controlled HTTP transport. Tests checked the server-side bearer header, bounded model request, ordered multi-turn context and completion cap. The key was absent from exposed SSE. |
| Incremental SSE and cancellation | Tests verified persisted deltas and terminal SSE events; interrupted client replay resumed after its last cursor. A live application cancellation request closed a paused test upstream stream. |
| Provider and usage handling | Simulated upstream 429, 401, 500, interrupted response and read timeout produced explicit safe application states. Tests stored 75 input and 12 output tokens when reported, and marked usage unavailable when omitted. |
| Budget and context | Tests exercised truncation and independent per-user and deployment budget checks. Mock mode is labeled in the workspace and saved answers. |
| Conversation and UI behavior | Browser tests exercised history and responsive search, prompt editing, cancellation and retry, regeneration, soft deletion and restoration, safe Markdown and code highlighting. |

**19 Pytest tests passed.** Playwright passed **4** tests across the desktop and two mobile widths. Two duplicate mobile runs of the desktop-specific action suite were intentionally skipped. [Provider worker tests](../../apps/ai-chat/api/tests/test_upstream_worker.py) · [Migration test](../../apps/ai-chat/api/tests/test_legacy_migration.py)

A live request to OpenAI is pending a deployment with an operator-supplied key and configured model. The browser demonstration and CI use labeled Mock mode. The real adapter's request and streaming behavior is covered by synthetic upstream tests.
