import hashlib
import json
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import engine, query, row, rows
from app.schemas import Credentials, MessageInput, Title
from app.worker import event, finish, work

log = logging.getLogger("uvicorn.error.chatflow")
passwords = PasswordHasher()
dummy_hash = passwords.hash(secrets.token_urlsafe(32))
COOKIE = "chatflow_session"
SECURE_COOKIE = os.getenv("COOKIE_SECURE", "1") == "1"
ORIGINS = set(os.getenv("APP_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
MAX_BODY = 32768

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

app = FastAPI(title="ChatFlow API", version="0.1.0", lifespan=lifespan)

def error(status, code, headers=None):
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=headers)

@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return error(exc.status_code, exc.detail, exc.headers)

@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return error(422, "invalid_input")

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    log.error("database request failed")
    return error(503, "database_unavailable")

@app.exception_handler(Exception)
async def server_error(request, exc):
    log.error("request failed error_type=%s", type(exc).__name__)
    return error(500, "internal_error")

@app.middleware("http")
async def guard(request: Request, call_next):
    identifier = uuid4().hex
    start = time.monotonic()
    if request.method in {"POST", "PATCH", "DELETE"}:
        if request.headers.get("origin") not in ORIGINS:
            response = error(403, "origin_denied")
        else:
            length = request.headers.get("content-length")
            if request.method in {"POST", "PATCH"} and length is None:
                response = error(411, "length_required")
            elif length and (not length.isdecimal() or int(length) > MAX_BODY):
                response = error(413, "body_too_large")
            else:
                response = await call_next(request)
    else:
        response = await call_next(request)
    response.headers["X-Request-ID"] = identifier
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/v1/") and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    log.info("request=%s method=%s status=%s ms=%d", identifier, request.method,
             response.status_code, (time.monotonic() - start) * 1000)
    return response

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def consume(conn, bucket, maximum):
    window = int(time.time() // 60)
    hit = query(conn, """INSERT INTO rate_limits VALUES (:bucket,:window,1)
                         ON CONFLICT (bucket,minute_bucket) DO UPDATE SET used=rate_limits.used+1
                         WHERE rate_limits.used < :maximum RETURNING used""",
                bucket=bucket, window=window, maximum=maximum).first()
    if not hit:
        raise HTTPException(429, "rate_limited", headers={"Retry-After": str(60 - int(time.time()) % 60)})

def auth_limit(request, email):
    address = request.client.host if request.client else "unknown"
    with engine.begin() as conn:
        consume(conn, "auth:ip:" + digest(address), 20)
        consume(conn, "auth:account:" + digest(email), 8)

def new_session(conn, response, user_id):
    token = secrets.token_urlsafe(32)
    query(conn, """INSERT INTO auth_sessions VALUES (:token,:user,now()+interval '7 days')""",
          token=digest(token), user=user_id)
    response.set_cookie(COOKIE, token, httponly=True, secure=SECURE_COOKIE,
                        samesite="lax", max_age=7 * 86400, path="/")

def user(request: Request):
    token = request.cookies.get(COOKIE)
    if token and len(token) <= 128:
        with engine.connect() as conn:
            account = row(conn, """
                SELECT u.id,u.email FROM auth_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=:token AND s.expires_at>now()""", token=digest(token))
            if account:
                return dict(account)
    raise HTTPException(401, "authentication_required")

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/readyz")
def readiness():
    with engine.connect() as conn:
        query(conn, "SELECT 1 FROM generations LIMIT 1")
    return {"status": "ready"}

@app.post("/v1/auth/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    auth_limit(request, body.email)
    identity = uuid4()
    password_hash = passwords.hash(body.password)
    with engine.begin() as conn:
        inserted = query(conn, """INSERT INTO users(id,email,password_hash) VALUES (:id,:email,:hash)
                                  ON CONFLICT (email) DO NOTHING RETURNING id""",
                         id=identity, email=body.email, hash=password_hash).first()
        if not inserted:
            raise HTTPException(409, "account_exists")
        new_session(conn, response, identity)
    return {"id": identity, "email": body.email}

@app.post("/v1/auth/login")
def login(body: Credentials, request: Request, response: Response):
    auth_limit(request, body.email)
    with engine.connect() as conn:
        account = row(conn, "SELECT * FROM users WHERE email=:email", email=body.email)
    try:
        passwords.verify(account["password_hash"] if account else dummy_hash, body.password)
    except VerificationError:
        raise HTTPException(401, "invalid_credentials") from None
    if not account:
        raise HTTPException(401, "invalid_credentials")
    with engine.begin() as conn:
        new_session(conn, response, account["id"])
    return {"id": account["id"], "email": account["email"]}

@app.post("/v1/auth/logout", status_code=204)
def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token and len(token) <= 128:
        with engine.begin() as conn:
            query(conn, "DELETE FROM auth_sessions WHERE token_hash=:token", token=digest(token))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/", secure=SECURE_COOKIE, httponly=True, samesite="lax")
    return response

@app.get("/v1/me")
def identity(account=Depends(user)):
    return account

def owned(conn, conversation, account, lock=False):
    sql = "SELECT * FROM conversations WHERE id=:id AND owner_id=:owner"
    result = row(conn, sql + (" FOR UPDATE" if lock else ""),
                 id=conversation, owner=account["id"])
    if not result:
        raise HTTPException(404, "not_found")
    return dict(result)

@app.get("/v1/conversations")
def list_conversations(account=Depends(user)):
    with engine.connect() as conn:
        return [dict(item) for item in rows(conn, """
            SELECT id,title,updated_at FROM conversations WHERE owner_id=:owner
            ORDER BY updated_at DESC,id LIMIT 100""", owner=account["id"])]

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
        query(conn, "DELETE FROM conversations WHERE id=:id", id=conversation)
    return Response(status_code=204)

def active(conn, conversation):
    return row(conn, """SELECT id FROM generations WHERE conversation_id=:id
                        AND state IN ('queued','running')""", id=conversation)

@app.get("/v1/conversations/{conversation}/messages")
def messages(conversation: UUID, before: Optional[int] = Query(None, ge=1), account=Depends(user)):
    with engine.connect() as conn:
        owned(conn, conversation, account)
        items = rows(conn, """SELECT m.id,m.seq,m.role,m.content,m.state,g.id AS generation_id
                              FROM messages m LEFT JOIN generations g ON g.assistant_message_id=m.id
                              WHERE m.conversation_id=:id AND m.seq < :before
                              ORDER BY m.seq DESC LIMIT 101""", id=conversation,
                     before=before if before is not None else 2147483648)
    page = items[:100]
    return {"messages": [dict(item) for item in reversed(page)],
            "before": page[-1]["seq"] if len(items) > 100 else None}

@app.post("/v1/conversations/{conversation}/messages", status_code=202)
def submit(conversation: UUID, body: MessageInput, account=Depends(user)):
    with engine.begin() as conn:
        owned(conn, conversation, account, lock=True)
        previous = row(conn, """SELECT id,request_digest,state FROM generations
                                WHERE conversation_id=:id AND request_key=:key""",
                       id=conversation, key=body.request_key)
        fingerprint = digest(body.content)
        if previous:
            if previous["request_digest"] != fingerprint:
                raise HTTPException(409, "idempotency_conflict")
            return {"id": previous["id"], "state": previous["state"]}
        if active(conn, conversation):
            raise HTTPException(409, "generation_active")
        consume(conn, "send:" + str(account["id"]), 12)
        consume(conn, "send:global", 80)
        seq = query(conn, """SELECT coalesce(max(seq),0)+1 FROM messages WHERE conversation_id=:id""",
                    id=conversation).scalar_one()
        human, assistant, run = uuid4(), uuid4(), uuid4()
        query(conn, """INSERT INTO messages(id,conversation_id,seq,role,content,state) VALUES
                      (:human,:id,:seq,'user',:content,'complete'),
                      (:assistant,:id,:next,'assistant','','pending')""",
              human=human, assistant=assistant, id=conversation, seq=seq, next=seq+1, content=body.content)
        query(conn, """INSERT INTO generations(id,conversation_id,user_message_id,assistant_message_id,
                                               request_key,request_digest,state)
                       VALUES (:run,:id,:human,:assistant,:key,:digest,'queued')""",
              run=run, id=conversation, human=human, assistant=assistant,
              key=body.request_key, digest=fingerprint)
        event(conn, run, 1, "meta", {"generation_id": str(run), "message_id": str(assistant)})
        query(conn, "UPDATE conversations SET updated_at=now() WHERE id=:id", id=conversation)
        return {"id": run, "state": "queued"}

def generation(conn, conversation, run, account):
    result = row(conn, """SELECT g.id,g.state,g.error_code,
                         coalesce(g.finished_at >= now()-interval '15 minutes', true) AS replayable
                         FROM generations g JOIN conversations c ON g.conversation_id=c.id
                         WHERE g.id=:run AND c.id=:id AND c.owner_id=:owner""",
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
