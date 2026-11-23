import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest

from app.db import engine, query

BASE = os.getenv("CHATFLOW_TEST_BASE", "http://127.0.0.1:8000")
ORIGIN = os.getenv("CHATFLOW_TEST_ORIGIN", "http://127.0.0.1:5173")
PASSWORD = "test-password-only"

@pytest.fixture
def accounts():
    with httpx.Client(base_url=BASE, headers={"Origin": ORIGIN}, timeout=12) as a:
        with httpx.Client(base_url=BASE, headers={"Origin": ORIGIN}, timeout=12) as b:
            for client in (a, b):
                client.email = f"{uuid4()}@example.test"
                response = client.post("/v1/auth/register", json={"email": client.email, "password": PASSWORD})
                assert response.status_code == 201, response.text
                assert "httponly" in response.headers["set-cookie"].lower()
            yield a, b

def create(client):
    response = client.post("/v1/conversations", json={"title": "Isolation check"})
    assert response.status_code == 201
    return "/v1/conversations/" + response.json()["id"]

def start(client, path, key=None):
    return client.post(path + "/messages", json={"content": "How can we test streaming?",
                                               "request_key": key or str(uuid4())})

def frames(response):
    fields = {}
    for line in response.iter_lines():
        if not line and "event" in fields:
            yield int(fields["id"]), fields["event"], json.loads(fields["data"])
            fields = {}
        elif ": " in line:
            key, value = line.split(": ", 1)
            fields[key] = value

def test_auth_origin_and_revocation(accounts):
    a, _ = accounts
    assert a.get("/v1/me").json()["email"] == a.email
    assert a.post("/v1/auth/logout", json={}, headers={"Origin": "https://wrong.example"}).status_code == 403
    token = a.cookies.get("chatflow_session")
    assert a.post("/v1/auth/logout", json={}).status_code == 204
    assert a.get("/v1/me", headers={"Cookie": "chatflow_session=" + token}).status_code == 401
    assert a.post("/v1/auth/login", json={"email": a.email, "password": PASSWORD + "!"}).status_code == 401
    assert a.post("/v1/auth/login", json={"email": a.email, "password": PASSWORD}).status_code == 200

def test_ownership_and_conversation_crud(accounts):
    a, b = accounts
    path = create(a)
    assert b.get("/v1/conversations").json() == []
    assert b.get(path).status_code == 404
    assert b.get(path + "/messages").status_code == 404
    assert b.patch(path, json={"title": "Bad rename"}).status_code == 404
    assert b.delete(path).status_code == 404
    assert start(b, path).status_code == 404
    assert a.patch(path, json={"title": "Renamed"}).json()["title"] == "Renamed"
    assert a.delete(path).status_code == 204
    assert a.get(path).status_code == 404

def test_concurrent_idempotency_stream_interrupt_and_expiry(accounts):
    a, b = accounts
    path = create(a)
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(start, a, path, key) for _ in range(2)]
        responses = [request.result() for request in requests]
    assert [r.status_code for r in responses] == [202, 202]
    run = responses[0].json()["id"]
    assert responses[1].json()["id"] == run
    assert a.post(path + "/messages", json={"content": "Different", "request_key": key}).status_code == 409
    running = path + "/generations/" + run
    events = running + "/events"
    assert b.get(running).status_code == 404
    assert b.get(events).status_code == 404
    with a.stream("GET", events) as stream:
        assert stream.status_code == 200
        iterator = frames(stream)
        first = next(iterator)
        delta = next(iterator)
        assert first[:2] == (1, "meta")
        assert delta[:2] == (2, "delta")
    with a.stream("GET", events, headers={"Last-Event-ID": str(delta[0])}) as stream:
        remainder = list(frames(stream))
    ids = [item[0] for item in remainder]
    assert ids == list(range(delta[0] + 1, ids[-1] + 1))
    assert remainder[-1][1] == "done"
    history = a.get(path + "/messages").json()["messages"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[-1]["content"] == "".join(payload["text"] for _, kind, payload
                                             in [delta, *remainder] if kind == "delta")
    with engine.begin() as connection:
        query(connection, "UPDATE generations SET finished_at=now()-interval '16 minutes' WHERE id=:id", id=run)
    assert a.get(events).status_code == 410
    assert a.get(path + "/messages").json()["messages"][-1]["state"] == "complete"

def test_rate_limit_and_invalid_requests(accounts):
    a, _ = accounts
    assert a.post("/v1/conversations", json={"title": "  "}).status_code == 422
    path = create(a)
    assert a.post(path + "/messages", json={"content": "x" * 4001, "request_key": str(uuid4())}).status_code == 422
    for _ in range(19):
        assert a.post("/v1/conversations", json={"title": "Quota"}).status_code == 201
    response = a.post("/v1/conversations", json={"title": "Over quota"})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0

def test_generation_cancel_is_owned_and_idempotent(accounts):
    a, b = accounts
    path = create(a)
    run = start(a, path).json()["id"]
    resource = path + "/generations/" + run
    assert b.post(resource + "/cancel", json={}).status_code == 404
    result = a.post(resource + "/cancel", json={})
    assert result.status_code == 200
    assert result.json()["error_code"] == "generation_cancelled"
    assert a.post(resource + "/cancel", json={}).json() == result.json()
    with a.stream("GET", resource + "/events") as stream:
        assert list(frames(stream))[-1][1:] == (
            "error", {"state": "failed", "code": "generation_cancelled"})
    messages = a.get(path + "/messages").json()["messages"]
    assert messages[-1]["state"] == "failed"

def test_running_generation_deadline(accounts):
    a, _ = accounts
    path = create(a)
    run = start(a, path).json()["id"]
    resource = path + "/generations/" + run
    with a.stream("GET", resource + "/events") as stream:
        iterator = frames(stream)
        assert next(iterator)[1] == "meta"
        assert next(iterator)[1] == "delta"
        with engine.begin() as connection:
            query(connection, "UPDATE generations SET deadline=now()-interval '1 second' WHERE id=:id", id=run)
        assert list(iterator)[-1][1:] == ("error", {"state": "failed", "code": "generation_timeout"})
    assert a.get(resource).json()["error_code"] == "generation_timeout"
