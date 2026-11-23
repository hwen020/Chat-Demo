import asyncio
import json
import os
import threading
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app import worker
from app.db import engine, query, row, rows
from app.main import app
from app.providers import OpenAIProvider
from chatflow_shared.auth import digest


MODEL = "synthetic-openai-model"
DELTA = 'data: {"choices":[{"delta":{"content":"Grounded reply"}}]}\n\n'
USAGE = 'data: {"choices":[],"usage":{"prompt_tokens":75,"completion_tokens":12}}\n\n'
DONE = "data: [DONE]\n\n"


@pytest.fixture
def running_job():
    user, conversation, original, history, prompt, answer, run = (uuid4() for _ in range(7))
    token = uuid4().hex
    with engine.begin() as conn:
        query(conn, "INSERT INTO users(id,email,password_hash) VALUES (:id,:email,'unused')",
              id=user, email=f"{user}@example.test")
        query(conn, "INSERT INTO auth_sessions VALUES (:token,:user,now()+interval '1 hour')",
              token=digest(token), user=user)
        query(conn, "INSERT INTO conversations(id,owner_id,title) VALUES (:id,:user,'Worker verification')",
              id=conversation, user=user)
        query(conn, """INSERT INTO messages(id,conversation_id,seq,role,content,state) VALUES
                      (:original,:chat,1,'user','Prior synthetic prompt','complete'),
                      (:history,:chat,2,'assistant','Prior synthetic reply','complete'),
                      (:prompt,:chat,3,'user','Current synthetic prompt','complete'),
                      (:answer,:chat,4,'assistant','','pending')""",
              chat=conversation, original=original, history=history, prompt=prompt, answer=answer)
        job = dict(row(conn, """
            INSERT INTO generations(id,conversation_id,user_message_id,assistant_message_id,
                                    request_key,request_digest,state,model,output_limit)
            VALUES (:id,:chat,:prompt,:answer,:key,'synthetic','running',:model,128)
            RETURNING *""", id=run, chat=conversation, prompt=prompt, answer=answer, key=uuid4(), model=MODEL))
        worker.event(conn, run, 1, "meta", {"generation_id": str(run)})
    origin = os.getenv("APP_ORIGINS", "http://127.0.0.1:5173").split(",")[0]
    client = TestClient(app, headers={"Origin": origin}, cookies={"chatflow_session": token})
    try:
        yield job, client, f"/v1/conversations/{conversation}"
    finally:
        client.close()
        with engine.begin() as conn:
            query(conn, "DELETE FROM users WHERE id=:id", id=user)


def route_upstream(monkeypatch, handler):
    monkeypatch.setattr(worker, "API_KEY", "synthetic-test-key")
    monkeypatch.setattr(worker, "MODELS", {MODEL: object()})
    monkeypatch.setattr(worker, "OpenAIProvider",
                        lambda key: OpenAIProvider(key, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("include_usage", [True, False])
def test_worker_persists_upstream_deltas_and_reported_usage(running_job, monkeypatch, include_usage):
    job, client, path = running_job

    def upstream(request):
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        body = json.loads(request.content)
        assert [message["content"] for message in body["messages"]] == [
            "Prior synthetic prompt", "Prior synthetic reply", "Current synthetic prompt",
        ]
        assert body["max_completion_tokens"] == 128
        return httpx.Response(200, text=DELTA + (USAGE if include_usage else "") + DONE)

    route_upstream(monkeypatch, upstream)
    worker.generate(job, threading.Event())
    messages = client.get(path + "/messages").json()["messages"]
    answer = messages[-1]
    assert answer["content"] == "Grounded reply"
    assert answer["state"] == "complete"
    assert answer["model"] == MODEL
    assert answer["input_tokens"] == (75 if include_usage else None)
    assert answer["output_tokens"] == (12 if include_usage else None)
    assert answer["usage_status"] == ("reported" if include_usage else "unavailable")
    events = client.get(path + "/generations/" + str(job["id"]) + "/events")
    assert events.status_code == 200
    assert "event: delta" in events.text and "event: done" in events.text
    assert "synthetic-test-key" not in events.text


@pytest.mark.parametrize(("status", "code"), [
    (429, "provider_rate_limited"),
    (401, "provider_credentials"),
    (500, "generation_failed"),
    (None, "generation_timeout"),
])
def test_upstream_error_is_safe_and_retryable(running_job, monkeypatch, status, code):
    job, client, path = running_job

    def upstream(request):
        if status is None:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(status, text="untrusted provider response")

    route_upstream(monkeypatch, upstream)
    worker.generate(job, threading.Event())
    resource = path + "/generations/" + str(job["id"])
    assert client.get(resource).json()["error_code"] == code
    events = client.get(resource + "/events").text
    assert f'"code": "{code}"' in events
    assert "untrusted provider response" not in events
    answer = client.get(path + "/messages").json()["messages"][-1]
    assert answer["state"] == "failed" and answer["usage_status"] == "unavailable"


def test_api_cancel_closes_an_open_upstream_stream(running_job, monkeypatch):
    job, client, path = running_job
    blocked = threading.Event()
    closed = threading.Event()

    class PausedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield DELTA.encode()
            blocked.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    route_upstream(monkeypatch, lambda _: httpx.Response(200, stream=PausedStream()))
    thread = threading.Thread(target=worker.generate, args=(job, threading.Event()), daemon=True)
    thread.start()
    try:
        assert blocked.wait(3)
        started = time.monotonic()
        resource = path + "/generations/" + str(job["id"])
        assert client.post(resource + "/cancel", json={}).json()["error_code"] == "generation_cancelled"
        assert closed.wait(3)
        assert time.monotonic() - started < 3
        with engine.connect() as conn:
            kinds = rows(conn, "SELECT kind FROM stream_events WHERE generation_id=:id ORDER BY seq", id=job["id"])
        assert [item["kind"] for item in kinds] == ["meta", "delta", "error"]
    finally:
        thread.join(timeout=4)
    assert not thread.is_alive()
