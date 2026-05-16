"""
Background Delivery Worker
==========================
Runs as a separate process alongside the Django API server.
Polls the database every 5 seconds for events that are due for delivery.

Retry schedule (self-implemented, no queue library):
  - Attempt 1: immediately on ingestion (triggered by API view)
  - Attempt 2: 30 seconds after attempt 1
  - Attempt 3: 5 minutes (300s) after attempt 2
  - Attempt 4: 30 minutes (1800s) after attempt 3
  - After 4 total attempts all failed → status = dead

The worker picks up events where:
  - status IN ('pending', 'failed')
  - next_attempt_at IS NULL OR next_attempt_at <= NOW()

This means the worker also handles events whose immediate first delivery
(fired by the API view thread) somehow never ran, providing a safety net.
"""

import logging
import os
import sys
import time

import django
from django.utils import timezone

# Bootstrap Django before importing models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from django.db import transaction
from webhooks.delivery import attempt_delivery
from webhooks.models import Event

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WORKER] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds between database polls


def get_due_events():
    now = timezone.now()
    return Event.objects.filter(
        status__in=[Event.STATUS_PENDING, Event.STATUS_FAILED],
    ).filter(
        next_attempt_at__isnull=True
    ) | Event.objects.filter(
        status__in=[Event.STATUS_PENDING, Event.STATUS_FAILED],
        next_attempt_at__lte=now,
    )


def run():
    logger.info("Webhook delivery worker started.")
    logger.info(f"Polling every {POLL_INTERVAL}s for due events...")

    while True:
        try:
            with transaction.atomic():
                due = list(get_due_events().select_for_update(skip_locked=True))

            if due:
                logger.info(f"Found {len(due)} event(s) due for delivery.")

            for event in due:
                logger.info(f"Delivering event {event.id} (attempt {event.attempt_count + 1})")
                try:
                    attempt_delivery(event)
                except Exception as exc:
                    logger.exception(f"Unhandled error delivering event {event.id}: {exc}")

        except Exception as exc:
            # Never crash the worker; log and keep polling
            logger.exception(f"Worker poll error: {exc}")

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    run()
