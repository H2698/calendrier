from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('service-worker.js', views.service_worker, name='service-worker'),
    path(
        'api/cron/send-due-notifications/',
        views.send_due_notifications_api,
        name='send-due-notifications',
    ),
    path('notifications/', views.notifications_page, name='page'),
    path('api/notifications/', views.notifications_api, name='list'),
    path(
        'api/push-subscriptions/',
        views.push_subscription_api,
        name='push-subscriptions',
    ),
    path(
        'api/notifications/<uuid:notification_id>/read/',
        views.notification_read_api,
        name='read',
    ),
    path('api/notifications/read-all/', views.notifications_read_all_api, name='read-all'),
]
