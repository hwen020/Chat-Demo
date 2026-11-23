from alembic import op

revision = "0001"
down_revision = None

def upgrade():
    statements = (
        """CREATE TABLE users (
            id uuid PRIMARY KEY, email text UNIQUE NOT NULL, password_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""",
        """CREATE TABLE auth_sessions (
            token_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
            expires_at timestamptz NOT NULL)""",
        """CREATE TABLE conversations (
            id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
            title text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())""",
        "CREATE INDEX conversations_owner_updated ON conversations (owner_id, updated_at DESC, id)",
        """CREATE TABLE messages (
            id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
            seq int NOT NULL, role text NOT NULL CHECK (role IN ('user','assistant')),
            content text NOT NULL, state text NOT NULL CHECK (state IN ('pending','complete','failed')),
            UNIQUE (conversation_id, seq), UNIQUE (conversation_id, id))""",
        """CREATE TABLE generations (
            id uuid PRIMARY KEY, conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
            user_message_id uuid NOT NULL, assistant_message_id uuid NOT NULL,
            request_key uuid NOT NULL, request_digest text NOT NULL,
            state text NOT NULL CHECK (state IN ('queued','running','complete','failed')),
            created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
            deadline timestamptz NOT NULL DEFAULT now() + interval '60 seconds',
            error_code text, UNIQUE (conversation_id, request_key),
            FOREIGN KEY (conversation_id, user_message_id) REFERENCES messages (conversation_id,id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id, assistant_message_id) REFERENCES messages (conversation_id,id) ON DELETE CASCADE)""",
        """CREATE UNIQUE INDEX generations_one_active ON generations (conversation_id)
            WHERE state IN ('queued','running')""",
        """CREATE TABLE stream_events (
            generation_id uuid NOT NULL REFERENCES generations ON DELETE CASCADE,
            seq int NOT NULL, kind text NOT NULL CHECK (kind IN ('meta','delta','done','error')),
            payload jsonb NOT NULL, PRIMARY KEY (generation_id,seq))""",
        """CREATE TABLE rate_limits (
            bucket text NOT NULL, minute_bucket bigint NOT NULL, used int NOT NULL,
            PRIMARY KEY (bucket,minute_bucket))""",
    )
    for statement in statements:
        op.execute(statement)

def downgrade():
    for table in ("rate_limits", "stream_events", "generations", "messages",
                  "conversations", "auth_sessions", "users"):
        op.execute("DROP TABLE " + table)
