# API and SSE contract

JSON requests use the same browser origin and an HttpOnly cookie. POST/PATCH requests need a Content-Length and use a maximum 32 KiB. Authentication state changes require an allowed Origin, including local browser origins. All private responses are non-cacheable. Error bodies use `{"error":{"code":"..."}}`, with `Retry-After` on rate limits.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | /v1/auth/register | Create account and session via email and password |
| POST | /v1/auth/login | Create an authenticated session |
| POST | /v1/auth/logout | Revoke the presented cookie |
| GET | /v1/me | Return current account |
| GET, POST | /v1/conversations | List latest 100 or create with a title |
| GET, PATCH, DELETE | /v1/conversations/{id} | Read, rename, delete; active generation prevents deletion |
| GET | /v1/conversations/{id}/messages | Latest 100 messages; pass `before` for earlier pages |
| POST | /v1/conversations/{id}/messages | Submit `content` and UUID `request_key`; returns generation ID and state |
| GET | /v1/conversations/{id}/generations/{run} | Inspect run state and replay availability |
| GET | /v1/conversations/{id}/generations/{run}/events | Subscribe or replay SSE |
| POST | /v1/conversations/{id}/generations/{run}/cancel | Stop an owned generation; returns stable terminal state on retry |
| GET | /healthz, /readyz | Liveness and database readiness |

A repeated request with identical content and key returns its existing generation. Changed content with that key returns 409. Start a different generation after the active one terminates. Ownership checks apply to conversations, messages, generation metadata and event subscriptions.

The stream starts with `meta`, sends `delta` events and ends in `done` or `error`. Each persistent event is assigned a contiguous decimal ID scoped to its generation. Resume using `Last-Event-ID` or `?after=`, exclusive. Heartbeat comments have no IDs and do not advance the cursor. Events remain available for 15 minutes after terminal state; then reconnect gets HTTP 410 or a reset signal and the client reloads durable history. A browser disconnect does not cancel generation. Explicit cancellation keeps partial text and emits a terminal error event with code generation_cancelled. HTTP requests are capped at 70 seconds per subscription and the run deadline is 60 seconds. The worker marks interrupted runs failed when their deadline expires. OpenAPI is available at `/docs`.
