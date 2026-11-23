import os

from sqlalchemy import create_engine
from chatflow_shared.auth import query, row, rows

engine = create_engine(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://chatflow:chatflow@127.0.0.1:55432/chatflow"),
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)
