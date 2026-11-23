import os

from sqlalchemy import create_engine, text

engine = create_engine(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://chatflow:chatflow@127.0.0.1:55432/chatflow"),
    pool_pre_ping=True,
    connect_args={"connect_timeout": 3},
)

def query(conn, sql, **params):
    return conn.execute(text(sql), params)

def row(conn, sql, **params):
    return query(conn, sql, **params).mappings().first()

def rows(conn, sql, **params):
    return query(conn, sql, **params).mappings().all()
