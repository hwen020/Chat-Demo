from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app import db


def test_v11_schema_migrates_without_changing_history(monkeypatch):
    schema = "legacy_test_" + uuid4().hex
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    persistent = db.engine
    with persistent.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    legacy = create_engine(persistent.url, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr(db, "engine", legacy)
    user, chat, prompt, reply, run = (uuid4() for _ in range(5))
    try:
        command.upgrade(config, "0001")
        with legacy.begin() as conn:
            db.query(conn, "INSERT INTO users(id,email,password_hash) VALUES (:id,'legacy@example.test','fixture')",
                     id=user)
            db.query(conn, "INSERT INTO conversations(id,owner_id,title) VALUES (:id,:owner,'v1.1 history')",
                     id=chat, owner=user)
            db.query(conn, """INSERT INTO messages(id,conversation_id,seq,role,content,state) VALUES
                     (:prompt,:chat,1,'user','Old prompt','complete'),
                     (:reply,:chat,2,'assistant','Old reply','complete')""",
                     prompt=prompt, reply=reply, chat=chat)
            db.query(conn, """INSERT INTO generations(id,conversation_id,user_message_id,assistant_message_id,
                          request_key,request_digest,state)
                          VALUES (:id,:chat,:prompt,:reply,:key,'fixture','complete')""",
                     id=run, chat=chat, prompt=prompt, reply=reply, key=uuid4())
            db.query(conn, "INSERT INTO stream_events VALUES (:id,1,'done','{}'::jsonb)", id=run)

        for revision in ("head", "0001", "head"):
            if revision == "0001":
                command.downgrade(config, revision)
            else:
                command.upgrade(config, revision)
            with legacy.connect() as conn:
                result = db.rows(conn, "SELECT id,content FROM messages WHERE conversation_id=:id ORDER BY seq",
                                 id=chat)
                assert [(item["id"], item["content"]) for item in result] == [
                    (prompt, "Old prompt"), (reply, "Old reply"),
                ]
                assert db.row(conn, "SELECT kind FROM stream_events WHERE generation_id=:id", id=run)["kind"] == "done"
                if revision == "head":
                    assert db.row(conn, "SELECT model FROM generations WHERE id=:id", id=run)["model"] == "mock"
                    assert db.row(conn, "SELECT deleted_at FROM conversations WHERE id=:id", id=chat)["deleted_at"] is None
    finally:
        legacy.dispose()
        with persistent.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
