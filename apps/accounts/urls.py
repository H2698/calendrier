from django.contrib.auth import views as auth_views
from django.urls import path
from django.urls import reverse_lazy

from . import views
from .views import AgencyLoginView

app_name = 'accounts'

urlpatterns = [
    path('settings/', views.settings_page, name='settings'),
    path('team/', views.team_page, name='team'),
    path('team/<int:user_id>/', views.team_member_page, name='team-member'),
    path('team/<int:user_id>/delete/', views.team_member_delete_page, name='team-member-delete'),
    path('api/team/', views.team_api, name='team-api'),
    path('api/team/create/', views.team_create_api, name='team-create-api'),
    path('api/team/<int:user_id>/', views.team_detail_api, name='team-detail-api'),
    path('login/', AgencyLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='accounts/password_reset_form.html',
            email_template_name='accounts/password_reset_email.txt',
            subject_template_name='accounts/password_reset_subject.txt',
            success_url=reverse_lazy('accounts:password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='accounts/password_reset_done.html'
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='accounts/password_reset_confirm.html',
            success_url=reverse_lazy('accounts:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='accounts/password_reset_complete.html'
        ),
        name='password_reset_complete',
    ),
]
