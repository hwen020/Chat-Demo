import asyncio
from contextlib import suppress
import json
import logging
import threading
import time

from app.db import engine, query, row, rows
import httpx

from app.model_config import API_KEY, MODELS
from app.providers import MockProvider, OpenAIProvider, Usage

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

def still_running(conn, job):
    current = row(conn, "SELECT state,deadline<=now() AS expired FROM generations "
                        "WHERE id=:id FOR UPDATE", id=job["id"])
    if not current or current["state"] != "running":
        return False
    if current["expired"]:
        finish(conn, job, "failed", "generation_timeout")
        return False
    return True


async def receive(job, stop, provider, history):
    run = job["id"]
    seq = 2
    events = provider.events(history, job["model"], job["output_limit"])
    task = None
    try:
        while not stop.is_set():
            task = asyncio.create_task(anext(events))
            while not task.done() and not stop.is_set():
                await asyncio.wait({task}, timeout=0.25)
                if not task.done():
                    with engine.begin() as conn:
                        if not still_running(conn, job):
                            return
            if stop.is_set():
                return
            try:
                delta = task.result()
            except StopAsyncIteration:
                with engine.begin() as conn:
                    if still_running(conn, job):
                        finish(conn, job, "complete")
                return
            with engine.begin() as conn:
                if not still_running(conn, job):
                    return
                if isinstance(delta, Usage):
                    query(conn, "UPDATE generations SET input_tokens=:input,output_tokens=:output WHERE id=:id",
                          id=run, input=delta.input_tokens, output=delta.output_tokens)
                else:
                    query(conn, "UPDATE messages SET content=content || :delta WHERE id=:id",
                          id=job["assistant_message_id"], delta=delta)
                    event(conn, run, seq, "delta", {"text": delta})
                    seq += 1
    finally:
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await events.aclose()


def generate(job, stop):
    run = job["id"]
    try:
        if job["model"] == "mock":
            provider = MockProvider()
        elif API_KEY and job["model"] in MODELS:
            provider = OpenAIProvider(API_KEY)
        else:
            raise ValueError("model_unavailable")
        with engine.connect() as conn:
            history = [dict(message) for message in rows(conn, """
                SELECT role,content FROM messages
                WHERE conversation_id=:id AND NOT superseded AND state='complete'
                  AND seq>=:start AND seq<=(SELECT seq FROM messages WHERE id=:prompt)
                ORDER BY seq""", id=job["conversation_id"], start=job["context_start"],
                prompt=job["user_message_id"])]
        asyncio.run(receive(job, stop, provider, history))
    except Exception as exc:
        log.warning("generation failed run=%s error_type=%s", run, type(exc).__name__)
        code = "generation_timeout" if isinstance(exc, httpx.TimeoutException) else "generation_failed"
        with engine.begin() as conn:
            if still_running(conn, job):
                finish(conn, job, "failed", code)


def work(stop):
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
                generate(job, stop)
            else:
                stop.wait(0.15)
        except Exception:
            log.error("generation worker temporarily unavailable")
            stop.wait(1)
