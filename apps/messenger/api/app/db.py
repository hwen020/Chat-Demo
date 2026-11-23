import os

from sqlalchemy import create_engine
from chatflow_shared.auth import query, row, rows

engine = create_engine(
    os.getenv("DATABASE_URL", "postgresql+psycopg://messenger:messenger@127.0.0.1:55433/messenger"),
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
