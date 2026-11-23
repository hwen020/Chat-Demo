# Messenger acceptance

- Implementation commit `04f8685f04188465295cf4161e44ff2e5935d25e`. The browser ordering fix is `9c226aa`. [Messenger implementation on GitHub](https://github.com/hwen020/Chat-Demo/commit/04f8685f04188465295cf4161e44ff2e5935d25e)
- Stack, design decisions, architecture diagram and three English résumé descriptions. [Messenger architecture](architecture.md)
- Reproduction commands and test ports. [Messenger README](../../apps/messenger/README.md)
- Independent GitHub workflow and artifacts. [Messenger CI](https://github.com/hwen020/Chat-Demo/actions/workflows/messenger.yml)

## Local acceptance on 2026-11-23

Docker Compose on Windows started Nginx, Redis 7.4, PostgreSQL 17, and independent FastAPI containers `api-a` and `api-b`. Synthetic browser testing used Microsoft Edge. All tests ran with separate temporary volumes.

| Capability | Evidence |
| --- | --- |
| Two independent API instances and Nginx balancing | The proxy reached both instance IDs. An HTTP 101 upgrade through Nginx succeeded. Direct socket handshakes exposed distinct instance IDs. |
| Cross-instance bidirectional WebSocket send | A sent to B and B replied to A using WebSocket input. The receiver saw the same record and sequence returned by the sender's acknowledgment and REST history. |
| Commit before notification | Acknowledgments reported persisted PostgreSQL records. Only a successful commit schedules local and Redis signals. The subscriber queried committed records for delivery. |
| Concurrency and sequence order | 20 HTTP sends issued concurrently through the two APIs. Both sockets received 20 unique records in the same order as PostgreSQL. Duplicate request UUIDs returned the same message. |
| Delayed and duplicate delivery | The Playwright test buffered a real socket message until a later acknowledgment, delivered the same frame twice, and asserted one correctly ordered copy in the browser. |
| WebSocket recovery | A disconnected member replayed writes strictly after its last committed sequence. |
| Redis failure and recovery | The test stopped Redis, waited for both instances to report unsubscribed, committed a new message, and observed delivery through PostgreSQL replay. Both subscriptions recovered after Redis restarted, and notification counters advanced. |
| API restart and proxy failover | The test stopped API B, confirmed its socket closed and Nginx still served API A, then wrote another message. After B restarted, the existing session, chat membership, and complete history remained available. |
| Authorization | PostgreSQL-backed session and membership checks rejected a nonmember's direct history, group history and group WebSocket handshake. |

The distributed test captured **40 observations** from 20 concurrent writes delivered to two sockets. Request initiation to application receipt had p50 **196.9 ms**, p95 **272.9 ms**, and max **274.7 ms**. The Redis outage sample arrived after **881.6 ms** via PostgreSQL polling. These measurements describe the local run and workload.

The native PostgreSQL/API integration suite passed **2 tests**. The browser suite through Nginx passed **1 end-to-end test**, including direct and group chat, delayed duplicate frames, and history after reload. [Distributed test](../../services/messenger/verify.py)
