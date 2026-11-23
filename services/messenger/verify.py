"""Exercise two live API instances and inject failures into a disposable Compose project."""
import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

ROOT = Path(__file__).resolve().parents[2]
PROXY = os.getenv("MESSENGER_WEB", "http://127.0.0.1:8081")
A = "http://127.0.0.1:" + os.getenv("MESSENGER_TEST_PORT_A", "18091")
B = "http://127.0.0.1:" + os.getenv("MESSENGER_TEST_PORT_B", "18092")
PASSWORD = "synthetic-distributed-test"


async def compose(project, *args):
    command = ["docker", "compose", "-p", project, "-f", "docker-compose.yml",
               "-f", "services/messenger/test.compose.yml", *args]
    await asyncio.to_thread(subprocess.run, command, check=True, cwd=ROOT, timeout=45)


async def await_status(client, predicate):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            response = await client.get("/readyz")
            if response.status_code == 200 and predicate(response.json()):
                return response.json()
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.25)
    raise AssertionError(f"Timed out waiting for readiness at {client.base_url}")


async def account(client):
    email = f"{uuid4()}@example.test"
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    return response.json()


async def create(client, emails, title=""):
    response = await client.post("/v1/chats", json={"emails": emails, "title": title})
    assert response.status_code == 201, response.text
    return "/v1/chats/" + response.json()["id"]


def socket(client, chat, after=0, base=None):
    host = (base or str(client.base_url)).rstrip("/").replace("http://", "ws://", 1)
    cookie = client.cookies.get("messenger_session")
    return connect(f"{host}{chat}/live?after={after}", origin=PROXY,
                   additional_headers={"Cookie": "messenger_session=" + cookie}, open_timeout=5)


def payload(content):
    return {"content": content, "request_key": str(uuid4())}


async def send(client, chat, body):
    response = await client.post(chat + "/messages", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def receive(websocket, match=lambda frame: "seq" in frame):
    async def read():
        while True:
            frame = json.loads(await websocket.recv())
            if match(frame):
                return frame
    return await asyncio.wait_for(read(), timeout=6)


async def read_messages(websocket, count, starts=None):
    frames, latencies = [], []
    for _ in range(count):
        frame = await receive(websocket)
        frames.append(frame)
        if starts is not None:
            latencies.append((time.perf_counter() - starts[frame["content"]]) * 1000)
    return frames, latencies


async def history(client, chat):
    response = await client.get(chat + "/messages")
    assert response.status_code == 200, response.text
    return response.json()["messages"]


def latency_summary(samples):
    sorted_samples = sorted(samples)
    return {"samples": len(samples), "p50_ms": round(statistics.median(samples), 1),
            "p95_ms": round(sorted_samples[(95 * len(samples) + 99) // 100 - 1], 1),
            "max_ms": round(max(samples), 1)}


async def exercise(project):
    headers = {"Origin": PROXY}
    async with (
        httpx.AsyncClient(base_url=A, headers=headers, timeout=5) as alice,
        httpx.AsyncClient(base_url=B, headers=headers, timeout=5) as bob,
        httpx.AsyncClient(base_url=A, headers=headers, timeout=5) as carol,
        httpx.AsyncClient(base_url=B, headers=headers, timeout=5) as outsider,
        httpx.AsyncClient(base_url=PROXY, timeout=5) as proxy,
    ):
        before_a, before_b = await asyncio.gather(
            await_status(alice, lambda status: status["redis_subscribed"]),
            await_status(bob, lambda status: status["redis_subscribed"]),
        )
        assert before_a["instance"] == "api-a" and before_b["instance"] == "api-b"
        await await_status(proxy, lambda status: status["status"] == "ready")
        servers = {(await proxy.get("/readyz")).json()["instance"] for _ in range(8)}
        assert servers == {"api-a", "api-b"}, servers
        a, b, c, _ = await asyncio.gather(*(account(client) for client in (alice, bob, carol, outsider)))
        direct = await create(alice, [b["email"]])
        group = await create(alice, [b["email"], c["email"]], "Concurrent group")
        assert (await carol.get(direct + "/messages")).status_code == 404
        assert (await outsider.get(group + "/messages")).status_code == 404
        try:
            async with socket(outsider, group):
                raise AssertionError("A nonmember opened a group socket")
        except InvalidStatus as exc:
            assert exc.response.status_code == 403

        async with socket(alice, direct, base=PROXY) as via_proxy:
            assert via_proxy.response.headers["X-Messenger-Instance"] in servers
        async with socket(alice, direct) as a_ws, socket(bob, direct) as b_ws:
            assert a_ws.response.headers["X-Messenger-Instance"] == "api-a"
            assert b_ws.response.headers["X-Messenger-Instance"] == "api-b"
            first = payload("Cross-instance socket send")
            await a_ws.send(json.dumps(first))
            ack = await receive(a_ws, lambda frame: frame.get("type") == "ack")
            assert ack["request_key"] == first["request_key"]
            assert ack["message"] in await history(bob, direct)
            assert await receive(b_ws) == ack["message"]
            second = payload("Cross-instance socket reply")
            await b_ws.send(json.dumps(second))
            ack_b = await receive(b_ws, lambda frame: frame.get("type") == "ack")
            assert await receive(a_ws, lambda frame: frame.get("content") == second["content"]) == ack_b["message"]
            assert await send(alice, direct, first) == ack["message"]
            assert len(await history(alice, direct)) == 2

        starts = {}

        async def timed_send(client, message):
            body = payload(message)
            starts[message] = time.perf_counter()
            return await send(client, group, body)

        async with socket(alice, group) as a_ws, socket(bob, group) as b_ws:
            tasks = [asyncio.create_task(read_messages(ws, 20, starts)) for ws in (a_ws, b_ws)]
            writes = await asyncio.gather(*(timed_send(alice if n % 2 == 0 else bob, f"Concurrent {n}")
                                           for n in range(20)))
            (a_frames, a_ms), (b_frames, b_ms) = await asyncio.gather(*tasks)
        committed = sorted(writes, key=lambda message: message["seq"])
        assert committed == a_frames == b_frames == await history(carol, group)
        assert len({item["seq"] for item in committed}) == 20
        cursor = committed[-1]["seq"]
        for client, before in ((alice, before_a), (bob, before_b)):
            await await_status(client, lambda status: status["redis_notifications"] > before["redis_notifications"])

        disconnected = await send(alice, group, payload("Committed while Bob was disconnected"))
        async with socket(bob, group, cursor) as b_ws:
            assert await receive(b_ws) == disconnected
            await compose(project, "stop", "-t", "1", "messenger-redis")
            try:
                await asyncio.gather(*(await_status(client, lambda status: not status["redis_subscribed"])
                                      for client in (alice, bob)))
                outage_start = time.perf_counter()
                saved = await send(alice, group, payload("Committed during Redis outage"))
                assert await receive(b_ws) == saved
                outage_ms = (time.perf_counter() - outage_start) * 1000
                assert saved in await history(bob, group)
            finally:
                await compose(project, "start", "messenger-redis")
            resumed = await asyncio.gather(*(await_status(client, lambda status: status["redis_subscribed"])
                                             for client in (alice, bob)))
            post_recovery = await send(alice, group, payload("Redis subscription restored"))
            assert await receive(b_ws) == post_recovery
            for client, status in zip((alice, bob), resumed):
                await await_status(client, lambda current: current["redis_notifications"] > status["redis_notifications"])

            await compose(project, "stop", "-t", "1", "messenger-api-b")
            try:
                await asyncio.wait_for(b_ws.wait_closed(), timeout=6)
                assert b_ws.close_code is not None
                assert (await proxy.get("/readyz")).json()["instance"] == "api-a"
                during_restart = await send(alice, group, payload("Committed while API B was stopped"))
            finally:
                await compose(project, "start", "messenger-api-b")

        await await_status(bob, lambda status: status["redis_subscribed"])
        assert (await bob.get("/v1/me")).json()["id"] == b["id"]
        async with socket(bob, group, post_recovery["seq"]) as b_ws:
            assert await receive(b_ws) == during_restart
        assert (await history(bob, group))[-4:] == [disconnected, saved, post_recovery, during_restart]
        assert (await bob.get("/v1/chats")).json()
        report = {
            "api_instances": sorted(servers),
            "concurrent_commits": len(committed),
            "send_to_receive": latency_summary(a_ms + b_ms),
            "redis_outage_delivery_ms": round(outage_ms, 1),
            "redis_reconnect": "passed",
            "api_restart_and_cursor_replay": "passed",
            "authorization": "passed",
        }
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or not re.fullmatch(r"chatflow-messenger-[a-z0-9-]+", sys.argv[1]):
        raise SystemExit("Pass a disposable Compose project named chatflow-messenger-*.")
    asyncio.run(exercise(sys.argv[1]))
