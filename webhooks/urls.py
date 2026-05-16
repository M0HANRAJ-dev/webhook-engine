from django.urls import path
from .views import DashboardView, EventDetailView, EventListCreateView, EventRetryView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('events', EventListCreateView.as_view(), name='event-list-create'),
    path('events/<uuid:pk>', EventDetailView.as_view(), name='event-detail'),
    path('events/<uuid:pk>/retry', EventRetryView.as_view(), name='event-retry'),
]
