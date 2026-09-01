from django.urls import path

from . import views

app_name = 'calendar_app'

urlpatterns = [
    path('calendar/', views.calendar_page, name='calendar-page'),
    path('api/calendar/', views.calendar_api, name='calendar-api'),
    path('api/appointment-types/', views.appointment_types_api, name='types-api'),
    path('api/appointments/', views.appointments_api, name='appointments-api'),
    path(
        'api/appointments/<uuid:appointment_id>/',
        views.appointment_detail_api,
        name='appointment-detail-api',
    ),
    path(
        'api/appointments/<uuid:appointment_id>/move/',
        views.appointment_move_api,
        name='appointment-move-api',
    ),
    path(
        'api/appointments/<uuid:appointment_id>/cancel/',
        views.appointment_cancel_api,
        name='appointment-cancel-api',
    ),
    path(
        'api/appointments/<uuid:appointment_id>/delete/',
        views.appointment_delete_api,
        name='appointment-delete-api',
    ),
]
