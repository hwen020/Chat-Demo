# Messenger architecture

The React client uses same-origin REST for account management, conversation search, chat creation, sending, and paginated history. Each chat has a private WebSocket stream. The server revalidates the session and membership when it reads from PostgreSQL, and clients reconnect from their last observed sequence number.

A direct conversation has one unique key derived from its two account IDs. Creating a group records all memberships in the same transaction. Messages are serialized per chat, so sequence order follows commit order within the chat. The sender and request UUID form an idempotency key.

Messenger owns its PostgreSQL database and Alembic revisions. It imports shared authentication and validation utilities. It has no dependency on AI Chat's models, worker, or data.
