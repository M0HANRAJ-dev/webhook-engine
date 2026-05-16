import logging
import threading

from django.shortcuts import render
from django.utils import timezone
from django.views import View
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .delivery import attempt_delivery
from .models import Event
from .serializers import EventCreateSerializer, EventSerializer

logger = logging.getLogger(__name__)


class DashboardView(View):
    def get(self, request):
        return render(request, 'index.html')


def _deliver_in_background(event: Event):
    """Fire-and-forget first delivery attempt in a thread so the API response is instant."""
    try:
        attempt_delivery(event)
    except Exception as e:
        logger.exception(f"Unhandled error during immediate delivery of {event.id}: {e}")


class EventListCreateView(APIView):
    """
    POST /events  – ingest a new event and queue it immediately.
    GET  /events  – list all events (no attempt history for brevity).
    """

    def post(self, request):
        serializer = EventCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        event = serializer.save()

        # Attempt delivery immediately (non-blocking)
        t = threading.Thread(target=_deliver_in_background, args=(event,), daemon=True)
        t.start()

        out = EventSerializer(event)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def get(self, request):
        events = Event.objects.all()
        serializer = EventSerializer(events, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class EventDetailView(APIView):
    """GET /events/:id – single event with full attempt history."""

    def get(self, request, pk):
        try:
            event = Event.objects.prefetch_related('attempts').get(pk=pk)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = EventSerializer(event)
        return Response(serializer.data, status=status.HTTP_200_OK)


class EventRetryView(APIView):
    """POST /events/:id/retry – manually re-queue a dead event."""

    def post(self, request, pk):
        try:
            event = Event.objects.get(pk=pk)
        except Event.DoesNotExist:
            return Response({'error': 'Event not found.'}, status=status.HTTP_404_NOT_FOUND)

        if event.status != Event.STATUS_DEAD:
            return Response(
                {'error': 'Only dead events can be manually retried.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reset so the worker picks it up immediately
        event.status = Event.STATUS_PENDING
        event.attempt_count = 0
        event.next_attempt_at = timezone.now()
        event.save(update_fields=['status', 'attempt_count', 'next_attempt_at'])

        # Also trigger immediately in background
        t = threading.Thread(target=_deliver_in_background, args=(event,), daemon=True)
        t.start()

        return Response({'message': 'Event re-queued for delivery.', 'id': str(event.id)}, status=status.HTTP_200_OK)
