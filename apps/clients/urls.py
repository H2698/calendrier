from django.urls import path

from . import views

app_name = 'clients'

urlpatterns = [
    path('clients/', views.client_list_page, name='list'),
    path('clients/new/', views.client_create_page, name='create'),
    path('clients/<uuid:client_id>/', views.client_detail_page, name='detail'),
    path('clients/<uuid:client_id>/edit/', views.client_edit_page, name='edit'),
    path('api/clients/', views.clients_api, name='api-list'),
    path('api/clients/<uuid:client_id>/', views.client_detail_api, name='api-detail'),
    path(
        'api/clients/<uuid:client_id>/archive/',
        views.client_archive_api,
        name='api-archive',
    ),
]
