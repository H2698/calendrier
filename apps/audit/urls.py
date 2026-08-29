from django.urls import path

from .views import activity_api

app_name = 'audit'

urlpatterns = [path('api/activity/', activity_api, name='activity-api')]
