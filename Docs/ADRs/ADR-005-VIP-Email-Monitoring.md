# ADR-005 — VIP Community Email Monitoring (Fast-Path Election Sync Trigger)

**Status:** Accepted  
**Date:** 2026-05-18  
**Author:** Walter LeFort

---

## Context

The Google Civic Information API `/elections` endpoint is polled on a 6-hour schedule (ADR-002) to detect new election data. While reliable, this introduces up to a 6-hour lag between when a new election's data goes live in the Civic API and when CivicMirror starts serving it.

The **Voting Information Project (VIP) Community Google Group** (`groups.google.com/g/vip-community`) sends email announcements whenever election data goes live. These announcements follow a consistent, machine-parseable format:

```
Subject: [vip-community] {State} {Election Name} is now live
Body:    EID {electionId}  NID {nodeId}
         ...
```

**Identifiers (confirmed via VIP spec Issue #410 — "existing dual identification `eid` and `nid`"):**

| Identifier | Meaning | Public API Field |
|---|---|---|
| **EID** | Election ID — the public Google Civic API `electionId` | `/elections[].id` |
| **NID** | Node ID — Google's internal backend identifier for the data node | Not exposed in public API |

Since the EID maps directly to the Civic API `electionId`, a VIP email announcement is a reliable, near-real-time signal that `GET /voterinfo?electionId={EID}` will return populated data.

---

## Decision

**Subscribe a dedicated Gmail account to `vip-community@googlegroups.com` and use the Gmail API (Cloud Pub/Sub push) as a fast-path trigger for election sync — supplementing, not replacing, the scheduled 6-hour poll.**

### Architecture

```
VIP Community Google Group
         │  email announcement (EID XXXX NID XXXXXXXX)
         ▼
Gmail Inbox  (service Gmail account)
         │  Gmail API: users.watch() + Cloud Pub/Sub
         ▼
Cloud Pub/Sub Topic: civicmirror-vip-email
         │  push subscription → HTTPS POST
         ▼
POST /internal/tasks/sync-from-email/   ← same ADR-002 auth pattern
         │  parse EID from email body
         │  idempotency lock: sync_election:{eid}
         ▼
sync_election_races.delay(eid)
         │
         ▼
Google Civic Information API
```

This fits the existing ADR-002 Cloud Scheduler → HTTP endpoint → Celery pattern exactly. The only difference is the trigger source (Pub/Sub push instead of Cloud Scheduler).

---

## Implementation Details

### Gmail API Setup

1. Create a dedicated Gmail account (e.g., `civicmirror-vip@gmail.com`) subscribed to `vip-community@googlegroups.com`.
2. Create a Google Cloud Pub/Sub topic: `civicmirror-vip-email`.
3. Grant publish rights to `gmail-api-push@system.gserviceaccount.com` on the topic.
4. Create a Pub/Sub push subscription pointing to `POST /internal/tasks/sync-from-email/`.
5. Call `users.watch()` on the Gmail account to activate push notifications:

```python
gmail.users().watch(userId="me", body={
    "topicName": "projects/{project}/topics/civicmirror-vip-email",
    "labelIds": ["INBOX"],
    "labelFilterBehavior": "INCLUDE",
}).execute()
```

### watch Renewal

`watch()` expires every **7 days**. Add a Cloud Scheduler job to renew it daily:

```
POST /internal/tasks/renew-gmail-watch/
Schedule: daily at 00:00 UTC
```

### Email Parser

```python
import re
import base64

EID_PATTERN = re.compile(r"\bEID\s+(\d+)\b", re.IGNORECASE)

def extract_eid_from_gmail_message(message: dict) -> int | None:
    payload = message.get("payload", {})
    # Check subject line
    headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
    subject = headers.get("Subject", "")
    # Check body parts
    body = _decode_body_parts(payload)
    for text in (subject, body):
        match = EID_PATTERN.search(text)
        if match:
            return int(match.group(1))
    return None

def _decode_body_parts(payload: dict) -> str:
    parts = payload.get("parts", [payload])
    for part in parts:
        data = part.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""
```

### Internal Endpoint

```python
# POST /internal/tasks/sync-from-email/
# Auth: ADR-002 OIDC (prod) / INTERNAL_TASK_TOKEN (dev)

class SyncFromEmailView(InternalTaskView):
    def post(self, request):
        pubsub_message = request.data.get("message", {})
        data = base64.urlsafe_b64decode(pubsub_message.get("data", "") + "==")
        history_id = json.loads(data).get("historyId")

        eid = self._get_eid_from_history(history_id)
        if not eid:
            return Response({"status": "no_eid_found"}, status=200)  # ACK to Pub/Sub

        lock_key = f"sync_election:{eid}"
        if not acquire_idempotency_lock(lock_key, ttl=300):
            return Response({"status": "already_running"}, status=202)

        task = sync_election_races.delay(eid)
        log_sync_event("sync_from_email", eid=eid, task_id=task.id)
        return Response({"task_id": task.id, "eid": eid}, status=202)
```

**Important:** Always return `200` or `202` to Cloud Pub/Sub to acknowledge the message. Returning a non-2xx code causes Pub/Sub to retry indefinitely.

### Env Vars

```
GMAIL_SERVICE_ACCOUNT_JSON=<base64-encoded service account key>  # Secret Manager
VIP_GMAIL_WATCH_TOPIC=projects/{project}/topics/civicmirror-vip-email
GMAIL_WATCH_USER_ID=civicmirror-vip@gmail.com
```

---

## Safety Net: Scheduled Polling Unchanged

The email monitoring path is additive and does **not** replace the 6-hour scheduled sync:

| Trigger | Latency | Resilience |
|---|---|---|
| VIP email → Pub/Sub | ~2–10 minutes | Depends on VIP team posting + email delivery |
| Cloud Scheduler (6h) | Up to 6 hours | Deterministic, catches missed emails |

Elections missed by the email path (no announcement, VIP format change, delivery failure) are always caught by the scheduled poll.

---

## Consequences

**Positive:**
- Near-real-time election data availability (minutes vs. hours)
- Zero wasted Civic API calls — sync is triggered only when data is confirmed live
- Minimal infrastructure overhead — reuses Cloud Pub/Sub + existing internal endpoint pattern

**Negative / Risks:**
- **Fragile email parsing** — if VIP team changes the announcement format, extraction silently fails. Mitigated by: keeping scheduled poll, alerting on zero EID extracted over a rolling window.
- **Gmail `watch` expiry** — must be renewed every 7 days. Mitigated by daily renewal Cloud Scheduler job.
- **Pub/Sub at-least-once delivery** — may receive duplicate notifications. Mitigated by idempotency lock keyed on `sync_election:{eid}`.
- **Requires a Google account** subscribed to the group — a human admin must join the group with the service account email.

---

## Alternatives Considered

| Option | Rejected Reason |
|---|---|
| IMAP polling (App Passwords) | Less secure; polling adds latency; IMAP deprecated by Google |
| Scraping Google Groups web UI | JavaScript-rendered; fragile; violates ToS |
| Increase scheduled poll frequency (e.g., hourly) | 6× more Civic API calls, marginal improvement |
| Accept 6-hour polling lag only | Viable, but fast-path is low-cost and high-value |

---

## References

- [Gmail API Push Notifications](https://developers.google.com/gmail/api/guides/push)
- [VIP specification Issue #410](https://github.com/votinginfoproject/vip-specification/issues/410) — "existing dual identification `eid` and `nid`"
- [VIP Community Google Group](https://groups.google.com/g/vip-community)
- [ADR-002 — Scheduler Architecture](./ADR-002-Scheduler-Architecture.md)
