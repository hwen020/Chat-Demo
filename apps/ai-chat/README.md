# ChatFlow AI

## Public demo

AI Chat has a separate prepared Render Free deployment. Public URLs are pending account access. A first visit can take about one minute while a Free instance wakes. See [deployment and public acceptance](../../docs/public-demo.md).

A conversation workspace with a React and TypeScript frontend, FastAPI and a PostgreSQL-backed generation worker. It streams replies over replayable SSE and persists each conversation between visits.

## Quick start

From the repository root, run `docker compose up --build api` and open [AI Chat](http://127.0.0.1:8080). Register a sample account. Create a conversation, send a prompt, stop a reply, or edit a prior prompt and regenerate from that point. Deleted conversations are recoverable from **Recently deleted**.

The application displays **Mock active** when no API key is configured. Mock answers are deterministic and individually labeled, including older answers viewed after real mode is enabled.

## Enable OpenAI

Use the values in [.env.example](.env.example) through the server environment, the root `.env`, or `docker compose --env-file apps/ai-chat/.env up --build api`. An OpenAI API key and a nonempty `AI_OPENAI_MODELS` JSON mapping are both required for real mode. Each JSON key is an OpenAI text model ID. Each value is a pair of positive integers for input and output prices in **micro-USD per million tokens**. For example, a price of $0.50 per million tokens is entered as `500000`. Use the configured model's current official prices. [OpenAI API pricing](https://platform.openai.com/docs/pricing)

`OPENAI_API_KEY` is read by the API container only. The model selector displays only configured models. Real mode sends the bounded context to OpenAI and persists the model ID plus reported token usage when available. The history labels unreported token usage as unavailable. Upstream rate limits, timeouts and incomplete streams have separate error states and can be retried from the conversation. [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)

| Variable | Default | Enforcement |
| --- | --- | --- |
| `AI_MAX_INPUT_TOKENS` | `8192` | Conservative UTF-8 byte count plus message overhead. The oldest context is dropped first and the latest prompt must fit. |
| `AI_MAX_OUTPUT_TOKENS` | `1024` | Sent as the provider's maximum completion tokens, including any reasoning tokens. |
| `AI_USER_DAILY_MICROUSD` | `250000` | Per-account daily admission budget, equivalent to $0.25. |
| `AI_GLOBAL_DAILY_MICROUSD` | `2000000` | Deployment-wide daily admission budget, equivalent to $2.00. |

Budget admission reserves the estimated input cost plus the maximum output cost before queuing each real request. PostgreSQL serializes admission across processes and counts reservations until midnight UTC, including cancelled and failed requests. The calculation uses configured prices and local token estimates. Configure appropriate limits in the provider account as well. Mock messages cost zero and use the existing per-minute send limits.

## Version and test evidence

The API pins FastAPI 0.133.0 and Starlette 1.3.1 in [requirements.txt](api/requirements.txt). CI runs browser and REST/SSE integration tests against labeled Mock mode. The OpenAI adapter also has controlled HTTP transport tests for incremental deltas, usage, timeouts, rate limits and cancellation. A live OpenAI smoke test needs an operator-configured server key and model. Results for each evidence type are recorded in the [acceptance report](../../docs/ai-chat/acceptance.md).

To reproduce local Mock SSE timings, run `python -m pytest -s -k context_edit_retry_delete_and_restore` against the disposable test deployment. It measures three client submissions through first delta and completion.

## Native development and tests

Use Python 3.12, Node.js 22 and a dedicated PostgreSQL 17 database. In `apps/ai-chat/web`, run `npm ci` and `npm run build`. Set `DATABASE_URL` to the SQLAlchemy PostgreSQL URL, `PYTHONPATH` to the absolute path to `packages/shared/python`, and `STATIC_DIR` to the absolute path to `apps/ai-chat/web/dist`. Use `APP_ORIGINS=http://127.0.0.1:8000` and `COOKIE_SECURE=0` for local HTTP.

From `apps/ai-chat/api`:

```sh
python -m pip install -r requirements-test.txt
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

For HMR, run `npm run dev` from `web/` and allow that exact origin. For API integration tests, use an isolated Mock deployment and set `CHATFLOW_TEST_BASE` and `CHATFLOW_TEST_ORIGIN` to its API address. Run `python -m pytest -q` in `api/`. The replay expiry test deliberately updates a record. For browser tests, set `CHATFLOW_WEB` to the frontend URL and run `npx playwright install chromium` and `npm test` in `web/`.

## Deploy and migrate

Build from the repository root with `docker build -f apps/ai-chat/Dockerfile -t chatflow-ai .`. Use HTTPS, an exact HTTPS `APP_ORIGINS`, secure cookies, and deployment-managed secrets. Run `alembic upgrade head` against the AI database before starting the container. Allow streaming without proxy buffering, with an idle timeout above the 10-second heartbeat. Health probes use `/healthz` and `/readyz`. Compose continues to use the existing `chatflow_database` volume. See [migration and architecture notes](../../docs/ai-chat/workspace.md) and the [acceptance report](../../docs/ai-chat/acceptance.md).

This branch requires a Docker build context at the repository root. The existing Render service and Demo should continue to run their current deployment until a deliberate rollout is scheduled.
