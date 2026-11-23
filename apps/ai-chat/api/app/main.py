import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.db import engine, query, row, rows
from app.model_config import MODELS, INPUT_LIMIT, OUTPUT_LIMIT, context_window, reserve
from app.schemas import MessageInput, Title
from app.worker import event, finish, work
from chatflow_shared.auth import consume, digest, install_auth


@asynccontextmanager
async def lifespan(app):
    stop = threading.Event()
    worker = threading.Thread(target=work, args=(stop,), daemon=True, name="generation-worker")
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=4)

app = FastAPI(title="ChatFlow AI", version="1.0.0", lifespan=lifespan)

user, _ = install_auth(app, engine, "chatflow_session")


@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/readyz")
def readiness():
    with engine.connect() as conn:
        query(conn, "SELECT 1 FROM generations LIMIT 1")
    return {"status": "ready"}

@app.get("/v1/models")
def models(account=Depends(user)):
    return {"models": list(MODELS), "mode": "mock" if "mock" in MODELS else "openai",
            "input_limit": INPUT_LIMIT, "output_limit": OUTPUT_LIMIT}


def owned(conn, conversation, account, lock=False, deleted=False):
    sql = """SELECT * FROM conversations WHERE id=:id AND owner_id=:owner
        AND (deleted_at IS NOT NULL)=:deleted"""
    result = row(conn, sql + (" FOR UPDATE" if lock else ""),
                 id=conversation, owner=account["id"], deleted=deleted)
    if not result:
        raise HTTPException(404, "not_found")
    return dict(result)


@app.get("/v1/conversations")
def list_conversations(q: str = Query("", max_length=100), deleted: bool = False, account=Depends(user)):
    with engine.connect() as conn:
        return [dict(item) for item in rows(conn, """
            SELECT id,title,updated_at FROM conversations WHERE owner_id=:owner
              AND (deleted_at IS NOT NULL)=:deleted
              AND (:q='' OR strpos(lower(title),lower(:q))>0)
            ORDER BY updated_at DESC,id LIMIT 100""",
            owner=account["id"], deleted=deleted, q=q.strip())]


@app.post("/v1/conversations", status_code=201)
def create_conversation(body: Title, account=Depends(user)):
    with engine.begin() as conn:
        consume(conn, "create:" + str(account["id"]), 20)
        return dict(row(conn, """INSERT INTO conversations(id,owner_id,title)
                                 VALUES (:id,:owner,:title) RETURNING id,title,updated_at""",
                        id=uuid4(), owner=account["id"], title=body.title))

@app.get("/v1/conversations/{conversation}")
def get_conversation(conversation: UUID, account=Depends(user)):
    with engine.connect() as conn:
        item = owned(conn, conversation, account)
        del item["owner_id"]
        return item

@app.patch("/v1/conversations/{conversation}")
def rename(conversation: UUID, body: Title, account=Depends(user)):
    with engine.begin() as conn:
        owned(conn, conversation, account, lock=True)
        return dict(row(conn, """UPDATE conversations SET title=:title,updated_at=now()
                                 WHERE id=:id RETURNING id,title,updated_at""",
                        title=body.title, id=conversation))

@app.delete("/v1/conversations/{conversation}", status_code=204)
def delete(conversation: UUID, account=Depends(user)):
    with engine.begin() as conn:
        owned(conn, conversation, account, lock=True)
        if active(conn, conversation):
            raise HTTPException(409, "generation_active")
        query(conn, "UPDATE conversations SET deleted_at=now() WHERE id=:id", id=conversation)
    return Response(status_code=204)

@app.post("/v1/conversations/{conversation}/restore")
def restore(conversation: UUID, account=Depends(user)):
    with engine.begin() as conn:
        owned(conn, conversation, account, lock=True, deleted=True)
        return dict(row(conn, """UPDATE conversations SET deleted_at=NULL,updated_at=now()
            WHERE id=:id RETURNING id,title,updated_at""", id=conversation))


def active(conn, conversation):
    return row(conn, """SELECT id FROM generations WHERE conversation_id=:id
                        AND state IN ('queued','running')""", id=conversation)

@app.get("/v1/conversations/{conversation}/messages")
def messages(conversation: UUID, before: Optional[int] = Query(None, ge=1), account=Depends(user)):
    with engine.connect() as conn:
        owned(conn, conversation, account)
        items = rows(conn, """SELECT m.id,m.seq,m.role,m.content,m.state,g.id AS generation_id,
                                     g.model,g.input_tokens,g.output_tokens,
                                     CASE WHEN g.model='mock' THEN 'mock'
                                          WHEN g.input_tokens IS NOT NULL AND g.output_tokens IS NOT NULL THEN 'reported'
                                          WHEN g.state IN ('queued','running') THEN 'pending'
                                          WHEN g.id IS NOT NULL THEN 'unavailable' END AS usage_status
                              FROM messages m LEFT JOIN generations g ON g.assistant_message_id=m.id
                              WHERE m.conversation_id=:id AND NOT m.superseded AND m.seq < :before
                              ORDER BY m.seq DESC LIMIT 101""", id=conversation,
                     before=before if before is not None else 2147483648)
    page = items[:100]
    return {"messages": [dict(item) for item in reversed(page)],
            "before": page[-1]["seq"] if len(items) > 100 else None}

@app.post("/v1/conversations/{conversation}/messages", status_code=202)
def submit(conversation: UUID, body: MessageInput, account=Depends(user)):
    return queue(conversation, body, account)


@app.post("/v1/conversations/{conversation}/regenerate/{prompt}", status_code=202)
def regenerate(conversation: UUID, prompt: UUID, body: MessageInput, account=Depends(user)):
    return queue(conversation, body, account, prompt)


def queue(conversation, body, account, prompt=None):
    with engine.begin() as conn:
        owned(conn, conversation, account, lock=True)
        previous = row(conn, """SELECT id,request_digest,state FROM generations
                                WHERE conversation_id=:id AND request_key=:key""",
                       id=conversation, key=body.request_key)
        identity = body.content if not (body.model or prompt) else json.dumps(
            [body.content, body.model, str(prompt) if prompt else None])
        fingerprint = digest(identity)
        if previous:
            if previous["request_digest"] != fingerprint:
                raise HTTPException(409, "idempotency_conflict")
            return {"id": previous["id"], "state": previous["state"]}
        if active(conn, conversation):
            raise HTTPException(409, "generation_active")
        model = MODELS.get(body.model) if body.model else next(iter(MODELS.values()))
        if not model:
            raise HTTPException(422, "model_unavailable")
        consume(conn, "send:" + str(account["id"]), 12)
        consume(conn, "send:global", 80)
        seq = query(conn, "SELECT coalesce(max(seq),0)+1 FROM messages WHERE conversation_id=:id",
                    id=conversation).scalar_one()
        human, assistant, run = uuid4(), uuid4(), uuid4()
        if prompt:
            target = row(conn, """SELECT seq FROM messages
                WHERE conversation_id=:id AND id=:prompt AND role='user' AND NOT superseded""",
                id=conversation, prompt=prompt)
            if not target:
                raise HTTPException(404, "not_found")
            query(conn, "UPDATE messages SET superseded=true WHERE conversation_id=:id AND seq>=:start",
                  id=conversation, start=target["seq"])
        query(conn, """INSERT INTO messages(id,conversation_id,seq,role,content,state) VALUES
                      (:human,:id,:seq,'user',:content,'complete'),
                      (:assistant,:id,:next,'assistant','','pending')""",
              human=human, assistant=assistant, id=conversation, seq=seq, next=seq+1, content=body.content)
        history = list(reversed(rows(conn, """SELECT seq,role,content FROM messages
            WHERE conversation_id=:id AND NOT superseded AND state='complete'
            ORDER BY seq DESC LIMIT 80""", id=conversation)))
        context_start, tokens = context_window(history)
        cost = reserve(conn, account["id"], model, tokens)
        query(conn, """INSERT INTO generations(id,conversation_id,user_message_id,assistant_message_id,
                                               request_key,request_digest,state,model,context_start,output_limit,
                                               reserved_cost_microusd)
                       VALUES (:run,:id,:human,:assistant,:key,:digest,'queued',:model,:context,:limit,:cost)""",
              run=run, id=conversation, human=human, assistant=assistant, key=body.request_key,
              digest=fingerprint, model=model.id, context=context_start, limit=OUTPUT_LIMIT, cost=cost)
        event(conn, run, 1, "meta", {"generation_id": str(run), "message_id": str(assistant)})
        query(conn, "UPDATE conversations SET updated_at=now() WHERE id=:id", id=conversation)
        return {"id": run, "state": "queued"}


def generation(conn, conversation, run, account):
    result = row(conn, """SELECT g.id,g.state,g.error_code,
                         coalesce(g.finished_at >= now()-interval '15 minutes', true) AS replayable
                         FROM generations g JOIN conversations c ON g.conversation_id=c.id
                         WHERE g.id=:run AND c.id=:id AND c.owner_id=:owner AND c.deleted_at IS NULL""",
                 run=run, id=conversation, owner=account["id"])
    if not result:
        raise HTTPException(404, "not_found")
    return dict(result)

@app.get("/v1/conversations/{conversation}/generations/{run}")
def status(conversation: UUID, run: UUID, account=Depends(user)):
    with engine.connect() as conn:
        return generation(conn, conversation, run, account)

@app.post("/v1/conversations/{conversation}/generations/{run}/cancel")
def cancel(conversation: UUID, run: UUID, account=Depends(user)):
    with engine.begin() as conn:
        generation(conn, conversation, run, account)
        job = row(conn, "SELECT * FROM generations WHERE id=:id FOR UPDATE", id=run)
        if not job:
            raise HTTPException(404, "not_found")
        if job["state"] in {"queued", "running"}:
            finish(conn, job, "failed", "generation_cancelled")
        return generation(conn, conversation, run, account)

def streams(conversation, run, account, cursor):
    started = heartbeat = time.monotonic()
    while time.monotonic() - started < 70:
        with engine.connect() as conn:
            state = generation(conn, conversation, run, account)
            if not state["replayable"]:
                yield 'event: reset\ndata: {"code":"replay_expired"}\n\n'
                return
            events = rows(conn, """SELECT seq,kind,payload FROM stream_events
                                  WHERE generation_id=:run AND seq>:cursor ORDER BY seq""",
                          run=run, cursor=cursor)
        for item in events:
            cursor = item["seq"]
            yield f'id: {cursor}\nevent: {item["kind"]}\ndata: {json.dumps(item["payload"])}\n\n'
            if item["kind"] in {"done", "error"}:
                return
        if state["state"] in {"complete", "failed"}:
            return
        if time.monotonic() - heartbeat >= 10:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        time.sleep(0.15)

@app.get("/v1/conversations/{conversation}/generations/{run}/events")
def stream(conversation: UUID, run: UUID, after: int = Query(0, ge=0),
           last_event_id: Optional[int] = Header(None, ge=0), account=Depends(user)):
    cursor = max(after, last_event_id or 0)
    with engine.connect() as conn:
        result = generation(conn, conversation, run, account)
        if not result["replayable"]:
            raise HTTPException(410, "replay_expired")
        maximum = query(conn, "SELECT coalesce(max(seq),0) FROM stream_events WHERE generation_id=:run",
                        run=run).scalar_one()
        if cursor > maximum:
            raise HTTPException(409, "invalid_cursor")
    return StreamingResponse(streams(conversation, run, account, cursor), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

static = Path(os.getenv("STATIC_DIR", "/app/web"))
if (static / "index.html").exists():
    @app.get("/c/{conversation}", include_in_schema=False)
    def conversation_page(conversation: UUID):
        return FileResponse(static / "index.html")

    app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
