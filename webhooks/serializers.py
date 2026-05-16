from rest_framework import serializers
from .models import Event, DeliveryAttempt


class DeliveryAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAttempt
        fields = ['attempted_at', 'http_status', 'outcome']


class EventSerializer(serializers.ModelSerializer):
    attempts = DeliveryAttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Event
        fields = ['id', 'type', 'payload', 'webhook_url', 'status', 'created_at', 'attempts']


class EventCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ['type', 'payload', 'webhook_url']

    def validate_webhook_url(self, value):
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError("webhook_url must be a valid HTTP/HTTPS URL.")
        return value
