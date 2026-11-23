import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from chatflow_shared.auth import PUBLIC_DEMO, query, row, rows

database_url = os.getenv("DATABASE_URL")
if PUBLIC_DEMO and not database_url:
    raise RuntimeError("Public demos require an isolated DATABASE_URL")

url = make_url(database_url or "postgresql+psycopg://messenger:messenger@127.0.0.1:55433/messenger")
if url.drivername in {"postgres", "postgresql"}:
    url = url.set(drivername="postgresql+psycopg")
if PUBLIC_DEMO and os.getenv("RENDER") == "true" and url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
    url = url.update_query_dict({"sslmode": "require"})

engine = create_engine(
    url,
    pool_pre_ping=True,
    hide_parameters=PUBLIC_DEMO,
    connect_args={"connect_timeout": 3},
    **({"pool_size": 3, "max_overflow": 2, "pool_timeout": 5} if PUBLIC_DEMO else {}),
)
