from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    for statement in (
        """CREATE TABLE users (
            id uuid PRIMARY KEY, email text UNIQUE NOT NULL, password_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE auth_sessions (
            token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
            expires_at timestamptz NOT NULL)""",
        """CREATE TABLE rate_limits (
            bucket text NOT NULL, minute_bucket bigint NOT NULL, used int NOT NULL,
            PRIMARY KEY (bucket, minute_bucket))""",
        """CREATE TABLE chats (
            id uuid PRIMARY KEY, title text, direct_key text UNIQUE,
            updated_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE members (
            chat_id uuid NOT NULL REFERENCES chats ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
            PRIMARY KEY (chat_id, user_id))""",
        "CREATE INDEX members_by_user ON members (user_id, chat_id)",
        """CREATE TABLE chat_messages (
            seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            chat_id uuid NOT NULL REFERENCES chats ON DELETE CASCADE,
            sender_id uuid NOT NULL REFERENCES users,
            request_key uuid NOT NULL, content text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (chat_id, sender_id, request_key))""",
        "CREATE INDEX messages_by_chat ON chat_messages (chat_id, seq)",
    ):
        op.execute(statement)


def downgrade():
    for table in ("chat_messages", "members", "chats", "rate_limits", "auth_sessions", "users"):
        op.execute("DROP TABLE " + table)
