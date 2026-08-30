from django.urls import path

from .views import activity_api, history_page

app_name = 'audit'

urlpatterns = [
    path('history/', history_page, name='history'),
    path('api/activity/', activity_api, name='activity-api'),
]
