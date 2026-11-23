from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade():
    for statement in (
        "ALTER TABLE conversations ADD COLUMN deleted_at timestamptz",
        "ALTER TABLE messages ADD COLUMN superseded boolean NOT NULL DEFAULT false",
        """ALTER TABLE generations
            ADD COLUMN model text NOT NULL DEFAULT 'mock',
            ADD COLUMN context_start int NOT NULL DEFAULT 1,
            ADD COLUMN output_limit int NOT NULL DEFAULT 1024,
            ADD COLUMN reserved_cost_microusd bigint NOT NULL DEFAULT 0,
            ADD COLUMN input_tokens int,
            ADD COLUMN output_tokens int""",
        """CREATE INDEX generation_budget_by_day ON generations (created_at)
            WHERE reserved_cost_microusd > 0""",
    ):
        op.execute(statement)


def downgrade():
    op.execute("DROP INDEX generation_budget_by_day")
    op.execute("""ALTER TABLE generations DROP COLUMN model, DROP COLUMN context_start,
               DROP COLUMN output_limit, DROP COLUMN reserved_cost_microusd,
               DROP COLUMN input_tokens, DROP COLUMN output_tokens""")
    op.execute("ALTER TABLE messages DROP COLUMN superseded")
    op.execute("ALTER TABLE conversations DROP COLUMN deleted_at")
