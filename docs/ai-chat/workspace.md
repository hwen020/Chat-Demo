# AI Chat workspace architecture

The original v1.1 HTTP, session and SSE architecture is documented in [the baseline architecture](architecture.md). The AI workspace adds server-managed model selection, upstream streaming, token and budget admission, and reversible conversation deletion.

## Data and generation

- The owner check applies to conversation history and generation status, cancellation and replay. A deleted conversation is hidden until its owner restores it.
- A request locks its conversation, checks its idempotency key, snapshots the starting sequence for context, and queues one generation. Editing or regenerating starts from the chosen user message and marks that message and its descendants superseded. The revised prompt and new answer are visible while the original rows remain stored.
- The worker reconstructs the bounded context, marks model provenance, stores deltas for replay, and checks cancellation and deadlines during upstream waits. Interrupted generation is persisted as incomplete. Replay expires after 15 minutes. History remains in PostgreSQL.
- Budget reservations use the operator's configured prices, the UTF-8 input estimate, the provider output cap and a shared PostgreSQL lock. The system retains reservations for cancelled requests so missing provider usage cannot reopen budget.
- Assistant Markdown renders through React, with raw HTML and remote images suppressed and URL sanitization enabled. Syntax highlighting comes from the Markdown stage. User messages render as escaped text.

## Upgrade and rollback

Migration `0002` adds defaults and nullable metadata to existing tables. Take a protected PostgreSQL backup and let any active generation finish before replacing the application. Run `alembic upgrade head` with the new image, then start it on the existing database. Never point Messenger at the AI database.

For rollback, stop new writers. If no 0002-specific writes occurred, run `alembic downgrade 0001` using the new image, then redeploy the previous image. The downgrade removes metadata, including deleted and superseded flags, so deleted conversations and old prompt versions can be visible on the old app. Once 0002-specific writes occur, keep the 0002 deployment while resolving application issues, or restore a protected pre-upgrade backup in a separate database and reconcile new writes before switching traffic. The downgrade does not delete the original message rows.
