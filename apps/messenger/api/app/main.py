import asyncio
import os
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from pydantic import Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.db import engine, query, row, rows
from chatflow_shared.auth import consume, install_auth
from chatflow_shared.schemas import Input, trim

app = FastAPI(title="ChatFlow Messenger", version="1.0.0")
user, origins = install_auth(app, engine, "messenger_session")


class ChatInput(Input):
    emails: Annotated[list[str], Field(min_length=1, max_length=15)]
    title: Annotated[str, Field(max_length=100)] = ""
    normalize = field_validator("title", mode="before")(trim)


class SendInput(Input):
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    request_key: UUID
    normalize = field_validator("content", mode="before")(trim)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready():
    with engine.connect() as conn:
        query(conn, "SELECT 1 FROM chats LIMIT 1")
    return {"status": "ready"}


def member(conn, chat, account):
    if not row(conn, "SELECT 1 FROM members WHERE chat_id=:chat AND user_id=:user",
               chat=chat, user=account["id"]):
        raise HTTPException(404, "chat_not_found")


@app.get("/v1/contacts")
def contacts(email: Annotated[str, Query(min_length=3, max_length=254)], account=Depends(user)):
    with engine.begin() as conn:
        consume(conn, "contacts:" + str(account["id"]), 30)
        result = row(conn, "SELECT email FROM users WHERE email=:email AND id<>:user",
                     email=email.strip().lower(), user=account["id"])
        return dict(result) if result else None


@app.get("/v1/chats")
def chats(q: Annotated[str, Query(max_length=100)] = "", account=Depends(user)):
    with engine.connect() as conn:
        return [dict(item) for item in rows(conn, """
            SELECT c.id, c.updated_at, c.direct_key IS NULL AS group_chat,
                coalesce(c.title, string_agg(u.email, ', ' ORDER BY u.email)
                    FILTER (WHERE u.id<>:user)) AS title,
                array_agg(u.email ORDER BY u.email) AS contacts
            FROM chats c JOIN members mine ON mine.chat_id=c.id AND mine.user_id=:user
            JOIN members m ON m.chat_id=c.id JOIN users u ON u.id=m.user_id
            GROUP BY c.id
            HAVING strpos(lower(coalesce(c.title, '')), lower(:q))>0
                   OR bool_or(strpos(u.email, lower(:q))>0 AND u.id<>:user)
                   OR :q=''
            ORDER BY c.updated_at DESC,c.id
            """, user=account["id"], q=q.strip())]


@app.post("/v1/chats", status_code=201)
def create_chat(body: ChatInput, account=Depends(user)):
    emails = sorted(set(email.strip().lower() for email in body.emails) - {account["email"]})
    if not emails or any(len(email) > 254 for email in emails) or (len(emails) > 1 and not body.title):
        raise HTTPException(422, "invalid_chat")
    with engine.begin() as conn:
        consume(conn, "create:" + str(account["id"]), 20)
        peers = rows(conn, "SELECT id FROM users WHERE email=ANY(:emails)", emails=emails)
        if len(peers) != len(emails):
            raise HTTPException(422, "unknown_contact")
        members = [account["id"], *(peer["id"] for peer in peers)]
        direct = ":".join(sorted(map(str, members))) if len(members) == 2 and not body.title else None
        chat = uuid4()
        inserted = row(conn, """
            INSERT INTO chats(id,title,direct_key) VALUES (:chat,:title,:direct)
            ON CONFLICT (direct_key) DO NOTHING RETURNING id
            """, chat=chat, title=body.title or None, direct=direct)
        if not inserted:
            existing = row(conn, "SELECT id FROM chats WHERE direct_key=:direct", direct=direct)
            return {"id": existing["id"]}
        for identity in members:
            query(conn, "INSERT INTO members VALUES (:chat,:user)", chat=chat, user=identity)
        return {"id": chat}


MESSAGE_SELECT = """SELECT m.seq,m.sender_id,u.email AS sender,m.content,m.created_at
    FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.chat_id=:chat"""


@app.get("/v1/chats/{chat}/messages")
def history(chat: UUID, before: Annotated[int | None, Query(ge=1, le=2**63-1)] = None,
            account=Depends(user)):
    with engine.connect() as conn:
        member(conn, chat, account)
        items = rows(conn, MESSAGE_SELECT + " AND m.seq<:before ORDER BY m.seq DESC LIMIT 51",
                     chat=chat, before=before or 2**63-1)
    return {"messages": [dict(item) for item in reversed(items[:50])],
            "before": items[49]["seq"] if len(items) > 50 else None}


@app.post("/v1/chats/{chat}/messages", status_code=201)
def send(chat: UUID, body: SendInput, account=Depends(user)):
    with engine.begin() as conn:
        member(conn, chat, account)
        query(conn, "SELECT id FROM chats WHERE id=:chat FOR UPDATE", chat=chat)
        prior = row(conn, MESSAGE_SELECT + " AND m.sender_id=:user AND m.request_key=:key",
                    chat=chat, user=account["id"], key=body.request_key)
        if prior:
            if prior["content"] != body.content:
                raise HTTPException(409, "idempotency_conflict")
            return dict(prior)
        consume(conn, "send:" + str(account["id"]), 60)
        result = row(conn, """INSERT INTO chat_messages(chat_id,sender_id,request_key,content)
                     VALUES (:chat,:user,:key,:content) RETURNING seq,sender_id,content,created_at""",
                     chat=chat, user=account["id"], key=body.request_key, content=body.content)
        query(conn, "UPDATE chats SET updated_at=now() WHERE id=:chat", chat=chat)
        return {**result, "sender": account["email"]}


def live_messages(socket, chat, cursor):
    account = user(socket)
    with engine.connect() as conn:
        member(conn, chat, account)
        return [dict(item) for item in rows(conn, MESSAGE_SELECT + """
            AND m.seq>:cursor ORDER BY m.seq LIMIT 100""", chat=chat, cursor=cursor)]


@app.websocket("/v1/chats/{chat}/live")
async def live(socket: WebSocket, chat: UUID, after: int = 0):
    if socket.headers.get("origin") not in origins or not 0 <= after <= 2**63-1:
        await socket.close(code=1008)
        return
    try:
        batch = await run_in_threadpool(live_messages, socket, chat, after)
        await socket.accept()
        while True:
            for item in batch:
                await socket.send_json(jsonable_encoder(item))
                after = item["seq"]
            try:
                event = await asyncio.wait_for(socket.receive(), timeout=0.5)
                if event["type"] == "websocket.disconnect":
                    return
                await socket.close(code=1008)
                return
            except asyncio.TimeoutError:
                batch = await run_in_threadpool(live_messages, socket, chat, after)
    except WebSocketDisconnect:
        return
    except HTTPException:
        await socket.close(code=1008)


static = Path(os.getenv("STATIC_DIR", "/app/web"))
if (static / "index.html").exists():
    app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
