import json
import logging
import threading
import time

from app.db import engine, query, row, rows
from app.providers import MockProvider

log = logging.getLogger("chatflow.worker")
REPLAY_MINUTES = 15

def event(conn, run, seq, kind, payload):
    query(conn, """INSERT INTO stream_events VALUES (:run,:seq,:kind,CAST(:payload AS jsonb))""",
          run=run, seq=seq, kind=kind, payload=json.dumps(payload))

def finish(conn, job, state, code=None):
    run = job["id"]
    seq = query(conn, "SELECT coalesce(max(seq),0)+1 FROM stream_events WHERE generation_id=:run",
                run=run).scalar_one()
    query(conn, """UPDATE generations SET state=:state, error_code=:code, finished_at=now()
                   WHERE id=:run""", run=run, state=state, code=code)
    query(conn, "UPDATE messages SET state=:state WHERE id=:id",
          id=job["assistant_message_id"], state=state)
    event(conn, run, seq, "done" if state == "complete" else "error",
          {"state": state, "code": code})

def claim():
    with engine.begin() as conn:
        for expired in rows(conn, """SELECT * FROM generations
                            WHERE state IN ('running','queued') AND deadline < now()
                            FOR UPDATE SKIP LOCKED"""):
            finish(conn, expired, "failed", "generation_timeout")
        job = row(conn, """SELECT * FROM generations WHERE state='queued'
                  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1""")
        if job:
            query(conn, "UPDATE generations SET state='running' WHERE id=:id", id=job["id"])
        return job

def generate(job, stop, provider):
    run = job["id"]
    try:
        with engine.connect() as conn:
            history = [
                dict(message) for message in reversed(rows(conn, """
                    SELECT role,content FROM messages
                    WHERE conversation_id=:id AND state='complete'
                    ORDER BY seq DESC LIMIT 20""", id=job["conversation_id"]))
            ]
        for seq, delta in enumerate(provider.stream(history), start=2):
            if stop.wait(0.11):
                return
            with engine.begin() as conn:
                current = row(conn, "SELECT state,deadline<=now() AS expired FROM generations "
                                    "WHERE id=:id FOR UPDATE", id=run)
                if not current or current["state"] != "running":
                    return
                if current["expired"]:
                    finish(conn, job, "failed", "generation_timeout")
                    return
                query(conn, "UPDATE messages SET content=content || :delta WHERE id=:id",
                      id=job["assistant_message_id"], delta=delta)
                event(conn, run, seq, "delta", {"text": delta})
        with engine.begin() as conn:
            current = row(conn, "SELECT state FROM generations WHERE id=:id FOR UPDATE", id=run)
            if current and current["state"] == "running":
                finish(conn, job, "complete")
    except Exception:
        log.error("generation failed run=%s", run)
        with engine.begin() as conn:
            current = row(conn, "SELECT state FROM generations WHERE id=:id FOR UPDATE", id=run)
            if current and current["state"] == "running":
                finish(conn, job, "failed", "generation_failed")

def work(stop):
    provider = MockProvider()
    last_cleanup = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() - last_cleanup > 60:
                with engine.begin() as conn:
                    query(conn, """
                        DELETE FROM stream_events USING generations
                        WHERE generation_id=generations.id
                        AND finished_at < now() - interval '15 minutes'
                    """)
                    query(conn, "DELETE FROM auth_sessions WHERE expires_at < now()")
                    query(conn, """DELETE FROM rate_limits
                                   WHERE minute_bucket < extract(epoch FROM now())::bigint / 60 - 120""")
                last_cleanup = time.monotonic()
            job = claim()
            if job:
                generate(job, stop, provider)
            else:
                stop.wait(0.15)
        except Exception:
            log.error("generation worker temporarily unavailable")
            stop.wait(1)
