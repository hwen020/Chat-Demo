"""Exercise the hosted-demo settings against an isolated test database."""
from contextlib import ExitStack
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

ORIGIN = "https://demo.example.test"


def register(client, email):
    return client.post("/v1/auth/register", json={
        "email": email,
        "password": "synthetic-test-password",
    })


with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
    assert client.get("/v1/demo").json() == {"enabled": True}
    for path in ("/docs", "/redoc", "/openapi.json", "/metrics"):
        assert client.get(path).status_code == 404
    assert client.get("/v1/me").status_code == 401
    assert register(client, "fixture@example.com").status_code == 422
    account = register(client, f"{uuid4()}@example.test")
    assert account.status_code == 201, account.text
    assert "httponly" in account.headers["set-cookie"].lower()
    assert "secure" in account.headers["set-cookie"].lower()
    assert client.post("/v1/auth/logout", json={}, headers={"Origin": "https://other.example.test"}).status_code == 403
    if "Messenger" in app.title:
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as peer:
            email = f"{uuid4()}@example.test"
            assert register(peer, email).status_code == 201
        response = client.post("/v1/chats", json={"emails": [email]})
        assert response.status_code == 201, response.text
        path = "wss://demo.example.test/v1/chats/" + response.json()["id"] + "/live"
        with ExitStack() as stack:
            for _ in range(3):
                stack.enter_context(client.websocket_connect(path, headers={"Origin": ORIGIN}))
            try:
                with client.websocket_connect(path, headers={"Origin": ORIGIN}):
                    raise AssertionError("Fourth concurrent socket was accepted")
            except WebSocketDisconnect:
                pass
        with client.websocket_connect(path, headers={"Origin": ORIGIN}):
            pass
    else:
        assert client.get("/v1/models").json()["mode"] == "mock"
print(f"{app.title} public configuration passed")
