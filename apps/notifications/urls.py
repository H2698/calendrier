from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('notifications/', views.notifications_page, name='page'),
    path('api/notifications/', views.notifications_api, name='list'),
    path(
        'api/notifications/<uuid:notification_id>/read/',
        views.notification_read_api,
        name='read',
    ),
    path('api/notifications/read-all/', views.notifications_read_all_api, name='read-all'),
]
