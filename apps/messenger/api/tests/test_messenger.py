from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app


ORIGIN = "http://127.0.0.1:5173"
PASSWORD = "synthetic-test-password"


@pytest.fixture
def accounts():
    clients = []
    for host, _ in enumerate(range(3), start=1):
        client = TestClient(app, headers={"Origin": ORIGIN}, client=(f"192.0.2.{host}", 50000))
        client.email = f"{uuid4()}@example.test"
        response = client.post("/v1/auth/register", json={"email": client.email, "password": PASSWORD})
        assert response.status_code == 201, response.text
        assert "httponly" in response.headers["set-cookie"].lower()
        clients.append(client)
    yield clients
    for client in clients:
        client.close()


def test_direct_group_search_history_and_websocket(accounts):
    alice, bob, carol = accounts
    direct = alice.post("/v1/chats", json={"emails": [bob.email]}).json()["id"]
    assert bob.post("/v1/chats", json={"emails": [alice.email]}).json()["id"] == direct
    assert alice.get("/v1/chats", params={"q": bob.email[:8]}).json()[0]["title"] == bob.email
    route = f"/v1/chats/{direct}"
    assert carol.get(route + "/messages").status_code == 404
    payload = {"content": "Synthetic direct message", "request_key": str(uuid4())}
    assert carol.post(route + "/messages", json=payload).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with carol.websocket_connect(route + "/live", headers={"Origin": ORIGIN}):
            pytest.fail("Nonmember admitted")
    with pytest.raises(WebSocketDisconnect):
        with bob.websocket_connect(route + "/live", headers={"Origin": "https://bad.example"}):
            pytest.fail("Foreign origin admitted")

    with bob.websocket_connect(route + "/live", headers={"Origin": ORIGIN}) as live:
        sent = alice.post(route + "/messages", json=payload)
        assert sent.status_code == 201, sent.text
        assert live.receive_json() == sent.json()
        assert alice.post(route + "/messages", json=payload).json() == sent.json()
    assert bob.get(route + "/messages").json()["messages"] == [sent.json()]
    with bob.websocket_connect(route + "/live?after=0", headers={"Origin": ORIGIN}) as replay:
        assert replay.receive_json() == sent.json()

    group = alice.post("/v1/chats", json={"emails": [bob.email, carol.email], "title": "Design Team"})
    assert group.status_code == 201, group.text
    assert carol.get("/v1/chats", params={"q": "design"}).json()[0]["group_chat"]
    group_route = f"/v1/chats/{group.json()['id']}/messages"
    assert carol.post(group_route, json=payload).status_code == 201
    assert bob.get(group_route).json()["messages"][0]["sender"] == carol.email


def test_session_revocation(accounts):
    alice, _, _ = accounts
    assert alice.get("/v1/me").json()["email"] == alice.email
    assert alice.post("/v1/auth/logout", headers={"Origin": "https://bad.example"}).status_code == 403
    assert alice.post("/v1/auth/logout").status_code == 204
    assert alice.get("/v1/chats").status_code == 401
    assert alice.post("/v1/auth/login", json={"email": alice.email, "password": PASSWORD}).status_code == 200


def test_message_search_cursor_and_isolation(accounts):
    alice, bob, outsider = accounts
    chat = alice.post("/v1/chats", json={"emails": [bob.email]}).json()["id"]
    path = f"/v1/chats/{chat}/messages"
    for index in range(53):
        content = f"Plan_100% {index}" if index < 52 else "unrelated"
        response = alice.post(path, json={"content": content, "request_key": str(uuid4())})
        assert response.status_code == 201
    first = bob.get(path, params={"q": " PLAN_100% "}).json()
    assert len(first["messages"]) == 50 and first["before"]
    rest = bob.get(path, params={"q": "plan_100%", "before": first["before"]}).json()
    assert [item["content"] for item in rest["messages"]] == ["Plan_100% 0", "Plan_100% 1"]
    assert rest["before"] is None
    assert outsider.get(path, params={"q": "plan"}).status_code == 404
    assert bob.get(path, params={"q": "x" * 101}).status_code == 422
    assert "messenger_redis_publish_errors_total" in bob.get("/metrics").text
