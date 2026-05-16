# Webhook Delivery Engine

A Django-based webhook delivery system that accepts events, delivers them via HTTP POST with HMAC-SHA256 signing, retries on failure using a fixed schedule, and exposes status/history endpoints.

---

## Setup

### Requirements
- Python 3.10+

### Install dependencies

```bash
pip install django djangorestframework requests
```

### Apply migrations

```bash
python manage.py migrate
```

---

## Running the System

The system has **two processes** that must run simultaneously.

### Terminal 1 — API Server

```bash
python manage.py runserver 8000
```

### Terminal 2 — Background Delivery Worker

```bash
python worker.py
```

The worker polls the database every 5 seconds for events due for delivery or retry.

---

## UI Dashboard

Open `src/index.html` directly in your browser (no build step needed).

It auto-refreshes every 5 seconds and lets you:
- Send new events with a custom type, payload, and webhook URL
- View all events with live status badges and stats
- Inspect full delivery attempt history for any event
- Manually retry dead events

> The API server must be running on `http://localhost:8000` for the UI to work.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/events` | Ingest a new event |
| `GET` | `/events` | List all events |
| `GET` | `/events/:id` | Get event with full attempt history |
| `POST` | `/events/:id/retry` | Manually retry a dead event |

### POST /events

```bash
curl -X POST http://localhost:8000/events \
  -H "Content-Type: application/json" \
  -d '{"type": "payment.failed", "payload": {"amount": 99}, "webhook_url": "https://your-server.com/hook"}'
```

Response `201`:
```json
{
  "id": "uuid",
  "type": "payment.failed",
  "payload": {"amount": 99},
  "webhook_url": "https://your-server.com/hook",
  "status": "pending",
  "created_at": "2025-01-01T00:00:00Z",
  "attempts": []
}
```

### GET /events/:id

```bash
curl http://localhost:8000/events/<uuid>
```

Response `200`:
```json
{
  "id": "uuid",
  "type": "payment.failed",
  "payload": {"amount": 99},
  "webhook_url": "https://your-server.com/hook",
  "status": "delivered",
  "created_at": "...",
  "attempts": [
    {"attempted_at": "...", "http_status": 500, "outcome": "failed"},
    {"attempted_at": "...", "http_status": 200, "outcome": "success"}
  ]
}
```

### POST /events/:id/retry

Only works for events with `status: dead`. Returns `400` otherwise.

```bash
curl -X POST http://localhost:8000/events/<uuid>/retry
```

---

## HMAC Signature Verification

Every outgoing webhook request includes an `X-Webhook-Signature` header.

### Signing key

Set in `core/settings.py`:
```python
WEBHOOK_SIGNING_KEY = 'whsec_super_secret_signing_key_change_in_production'
```

### Signature format

```
X-Webhook-Signature: sha256=<hex_digest>
```

The signature is `HMAC-SHA256(key, raw_request_body)`.

### How to verify on your server (Python example)

```python
import hashlib
import hmac

SIGNING_KEY = 'whsec_super_secret_signing_key_change_in_production'

def verify_webhook(request_body: bytes, signature_header: str) -> bool:
    expected = hmac.new(
        SIGNING_KEY.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    received = signature_header.removeprefix('sha256=')
    return hmac.compare_digest(expected, received)
```

### Node.js example

```js
const crypto = require('crypto');
const SIGNING_KEY = 'whsec_super_secret_signing_key_change_in_production';

function verifyWebhook(rawBody, signatureHeader) {
  const expected = crypto
    .createHmac('sha256', SIGNING_KEY)
    .update(rawBody)
    .digest('hex');
  const received = signatureHeader.replace('sha256=', '');
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(received));
}
```

---

## Retry Scheduling Approach

**No queue library is used.** All retry logic is implemented directly.

### Schedule

| Attempt | Triggered |
|---------|-----------|
| 1 (initial) | Immediately on event ingestion (background thread in API view) |
| 2 | 30 seconds after attempt 1 |
| 3 | 5 minutes (300s) after attempt 2 |
| 4 | 30 minutes (1800s) after attempt 3 |
| After 4 failures | Event marked `dead`, no more retries |

### Mechanism

Each `Event` row has a `next_attempt_at` timestamp and an `attempt_count` integer.

- On failure, `delivery.py` computes `now + RETRY_INTERVALS[attempt_count - 1]` and writes it to `next_attempt_at`.
- The worker (`worker.py`) polls every 5 seconds with:
  ```sql
  SELECT * FROM events
  WHERE status IN ('pending', 'failed')
    AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
  ```
- `next_attempt_at IS NULL` catches brand-new events that the immediate API thread might not have reached yet (safety net).
- `SELECT FOR UPDATE SKIP LOCKED` ensures no double-delivery if multiple worker processes run.

A 2xx response at any attempt immediately sets `status = delivered` and stops retries.

---

## Behaviour on Server Restart

### API Server

Stateless. Restarting the API server has no effect on delivery — all state lives in the SQLite database.

### Worker

The worker is **restartable without data loss**. On restart:

- Events mid-retry (status `failed`) retain their `next_attempt_at` timestamp in the database.
- When the worker comes back up, it picks up exactly where it left off: any event whose `next_attempt_at` has passed will be retried on the next poll cycle.
- **Gap risk**: if the worker is down for longer than a retry window (e.g. 30 minutes), those retries are delivered late rather than missed — the worker simply processes them immediately on next start.

### What is NOT handled

- Events whose **first delivery** was in-flight (inside the API view thread) when the server crashed will be re-attempted by the worker on its next poll, because their `next_attempt_at` is `NULL` and `status` is still `pending`. This means at most one duplicate delivery is possible in a crash scenario. For production use, idempotency on the receiving server is recommended.

---

## Event Status Reference

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet attempted or awaiting first attempt |
| `failed` | Last attempt failed; retry scheduled |
| `delivered` | Successfully delivered (2xx received) |
| `dead` | All 4 attempts exhausted; manual retry required |

---

## Project Structure

```
webhook-engine/
├── core/
│   ├── settings.py       # Config, signing key, retry intervals
│   └── urls.py           # Root URL routing
├── webhooks/
│   ├── models.py         # Event + DeliveryAttempt models
│   ├── serializers.py    # DRF serializers
│   ├── views.py          # API endpoint logic
│   ├── delivery.py       # HMAC signing + HTTP delivery
│   └── urls.py           # Endpoint URL patterns
├── worker.py             # Background delivery worker (run separately)
├── manage.py
└── README.md
```
