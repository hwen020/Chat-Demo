import asyncio
import json
import logging
import os
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager, suppress

from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

INSTANCE = os.getenv("MESSENGER_INSTANCE", "standalone")
REDIS_URL = os.getenv("MESSENGER_REDIS_URL")
CHANNEL = "chatflow:messenger:committed:v1"
REPLAY_INTERVAL = 2.0
log = logging.getLogger("uvicorn.error.messenger")


class Signals:
    def __init__(self):
        self.listeners: dict[str, set[asyncio.Event]] = defaultdict(set)
        self.subscribed = False
        self.notifications = 0
        self.publish_errors = 0
        self.queue_dropped = 0
        self.outbound: asyncio.Queue[str] = asyncio.Queue(maxsize=128)
        self.loop: asyncio.AbstractEventLoop | None = None

    @contextmanager
    def room(self, chat):
        key = str(chat)
        event = asyncio.Event()
        self.listeners[key].add(event)
        try:
            yield event
        finally:
            self.listeners[key].remove(event)
            if not self.listeners[key]:
                del self.listeners[key]

    def notify(self, chat):
        if self.loop:
            with suppress(RuntimeError):
                self.loop.call_soon_threadsafe(self.committed, str(chat))

    def committed(self, key):
        for listener in self.listeners.get(key, ()):
            listener.set()
        if self.subscribed:
            try:
                self.outbound.put_nowait(key)
            except asyncio.QueueFull:
                self.queue_dropped += 1

    async def publish(self):
        async with AsyncRedis.from_url(REDIS_URL, socket_connect_timeout=0.25, socket_timeout=0.25) as client:
            while True:
                key = await self.outbound.get()
                try:
                    async with asyncio.timeout(0.5):
                        await client.publish(CHANNEL, key)
                except (RedisError, OSError, TimeoutError):
                    self.publish_errors += 1
                    log.debug(json.dumps({"event": "redis_publish_failed", "instance": INSTANCE}))

    async def listen(self):
        async with AsyncRedis.from_url(
            REDIS_URL, socket_connect_timeout=0.5, socket_timeout=3, decode_responses=True,
        ) as client:
            while True:
                try:
                    async with client.pubsub() as subscription:
                        await subscription.subscribe(CHANNEL)
                        while True:
                            event = await subscription.get_message(timeout=1)
                            if event is None:
                                continue
                            if event["type"] == "subscribe":
                                self.subscribed = True
                            elif event["type"] == "message":
                                self.notifications += 1
                                for listener in self.listeners.get(event["data"], ()):
                                    listener.set()
                except (RedisError, OSError):
                    if self.subscribed:
                        log.warning(json.dumps({"event": "redis_subscription_lost", "instance": INSTANCE}))
                    self.subscribed = False
                    await asyncio.sleep(0.5)
                finally:
                    self.subscribed = False


@asynccontextmanager
async def lifespan(app):
    signals = Signals()
    signals.loop = asyncio.get_running_loop()
    app.state.signals = signals
    tasks = [asyncio.create_task(target()) for target in (signals.listen, signals.publish)] if REDIS_URL else []
    try:
        yield
    finally:
        signals.loop = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
