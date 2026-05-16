import uuid
from django.db import models


class Event(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_DELIVERED = 'delivered'
    STATUS_FAILED = 'failed'
    STATUS_DEAD = 'dead'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_DELIVERED, 'Delivered'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_DEAD, 'Dead'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=255)
    payload = models.JSONField()
    webhook_url = models.URLField(max_length=2048)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    # When the worker should next attempt delivery
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    # Total attempts made so far
    attempt_count = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.type} [{self.status}] {self.id}"


class DeliveryAttempt(models.Model):
    OUTCOME_SUCCESS = 'success'
    OUTCOME_FAILED = 'failed'

    OUTCOME_CHOICES = [
        (OUTCOME_SUCCESS, 'Success'),
        (OUTCOME_FAILED, 'Failed'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='attempts')
    attempted_at = models.DateTimeField(auto_now_add=True)
    http_status = models.IntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES)

    class Meta:
        ordering = ['attempted_at']
