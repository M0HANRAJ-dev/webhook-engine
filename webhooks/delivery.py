"""
Delivery engine: HMAC signing + HTTP delivery logic.
Shared by both the background worker and the views (for immediate first attempt).
"""
import hashlib
import hmac
import json
import logging
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .models import DeliveryAttempt, Event

logger = logging.getLogger(__name__)

RETRY_INTERVALS = settings.WEBHOOK_RETRY_INTERVALS  # [30, 300, 1800]
MAX_ATTEMPTS = 4  # 1 initial + 3 retries


def sign_payload(body: bytes) -> str:
    key = settings.WEBHOOK_SIGNING_KEY.encode('utf-8')
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def attempt_delivery(event: Event) -> bool:
    """
    Make one HTTP POST attempt to the event's webhook_url.
    Records a DeliveryAttempt and updates event state.
    Returns True if delivered successfully.
    """
    body = json.dumps({
        'id': str(event.id),
        'type': event.type,
        'payload': event.payload,
    }).encode('utf-8')

    signature = sign_payload(body)
    http_status = None
    outcome = DeliveryAttempt.OUTCOME_FAILED

    try:
        resp = requests.post(
            url=event.webhook_url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Webhook-Signature': f'sha256={signature}',
                'X-Webhook-Event': event.type,
                'X-Webhook-ID': str(event.id),
            },
            timeout=10,
        )
        http_status = resp.status_code
        if 200 <= http_status < 300:
            outcome = DeliveryAttempt.OUTCOME_SUCCESS
        else:
            logger.warning(f"[{event.id}] Non-2xx response: {http_status}")
    except requests.exceptions.Timeout:
        logger.warning(f"[{event.id}] Timeout")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[{event.id}] Request error: {e}")

    DeliveryAttempt.objects.create(event=event, http_status=http_status, outcome=outcome)

    event.attempt_count += 1
    success = outcome == DeliveryAttempt.OUTCOME_SUCCESS

    if success:
        event.status = Event.STATUS_DELIVERED
        event.next_attempt_at = None
    elif event.attempt_count >= MAX_ATTEMPTS:
        event.status = Event.STATUS_DEAD
        event.next_attempt_at = None
    else:
        event.status = Event.STATUS_FAILED
        interval = RETRY_INTERVALS[event.attempt_count - 1]
        event.next_attempt_at = timezone.now() + timedelta(seconds=interval)

    event.save(update_fields=['status', 'attempt_count', 'next_attempt_at'])
    logger.info(f"[{event.id}] attempt {event.attempt_count}: {outcome} (http={http_status})")
    return success
