from datetime import timedelta
import json

from django.contrib.auth import get_user_model
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .forms import (
    AgencySettingsForm,
    AppointmentTypeSettingsForm,
    EmailAuthenticationForm,
    NotificationSettingsForm,
    ProfileSettingsForm,
    TeamMemberEditForm,
    TeamMemberForm,
)
from .models import Profile
from .permissions import admin_required, calendar_manager_required, can_delete_team_member
from .services import (
    clear_login_failures,
    create_user_account,
    delete_team_member,
    login_blocked_until,
    login_throttle_key,
    record_login_failure,
    update_user_account,
)
from apps.calendar_app.models import Appointment
from apps.calendar_app.models import AppointmentType
from apps.calendar_app.services import refresh_appointment_statuses
from apps.audit.services import log_activity
from apps.core.models import AgencySettings


class AgencyLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self.throttle_key = login_throttle_key(
            request, request.POST.get('username', '')
        )
        if login_blocked_until(self.throttle_key):
            self.request_was_throttled = True
            form = self.get_form()
            form.add_error(
                None,
                'Trop de tentatives. Réessayez dans 15 minutes.',
            )
            response = self.form_invalid(form)
            response.status_code = 429
            return response
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        response = super().form_invalid(form)
        if self.request.method == 'POST' and not getattr(
            self, 'request_was_throttled', False
        ):
            key = getattr(
                self,
                'throttle_key',
                login_throttle_key(self.request, self.request.POST.get('username', '')),
            )
            if record_login_failure(key):
                response.status_code = 429
        return response

    def form_valid(self, form):
        clear_login_failures(self.throttle_key)
        return super().form_valid(form)


@login_required
def dashboard(request):
    data = _dashboard_data(request.user)
    return render(request, 'dashboard.html', data)


def _dashboard_data(user):
    refresh_appointment_statuses()
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7)
    queryset = Appointment.objects.filter(
        deleted_at__isnull=True,
    ).exclude(status=Appointment.Status.CANCELLED).select_related(
        'appointment_type', 'client'
    ).prefetch_related('members__profile')
    if user.profile.role == 'member':
        queryset = queryset.filter(members=user)
    today = queryset.filter(start_at__gte=today_start, start_at__lt=tomorrow).distinct()
    upcoming = queryset.filter(start_at__gte=now).distinct()
    return {
        'kpis': {
            'today': today.count(),
            'week': queryset.filter(start_at__gte=today_start, start_at__lt=week_end).distinct().count(),
            'shootings': queryset.filter(
                start_at__gte=today_start,
                appointment_type__name__iexact='Shooting',
            ).distinct().count(),
            'upcoming': upcoming.count(),
        },
        'today_appointments': list(today.order_by('start_at')[:10]),
        'upcoming_appointments': list(upcoming.order_by('start_at')[:5]),
    }


@require_GET
@login_required
def dashboard_api(request):
    data = _dashboard_data(request.user)
    return JsonResponse(
        {
            'kpis': data['kpis'],
            'today': [_dashboard_item(item) for item in data['today_appointments']],
            'upcoming': [_dashboard_item(item) for item in data['upcoming_appointments']],
        }
    )


def _dashboard_item(item):
    return {
        'id': str(item.id),
        'title': item.title,
        'type': item.appointment_type.name,
        'start_at': item.start_at.isoformat(),
        'end_at': item.end_at.isoformat(),
        'status': item.status,
        'members': [member.profile.full_name for member in item.members.all()],
    }


def _team_queryset():
    return get_user_model().objects.filter(
        profile__deleted_at__isnull=True,
    ).select_related('profile').order_by('profile__full_name')


@login_required
@calendar_manager_required
def team_page(request):
    form = TeamMemberForm(request.POST or None)
    if request.method == 'POST':
        if request.user.profile.role != Profile.Role.ADMIN:
            raise PermissionDenied
        if form.is_valid():
            try:
                create_user_account(actor=request.user, **form.cleaned_data)
            except ValidationError as exc:
                if hasattr(exc, 'message_dict'):
                    for field, errors in exc.message_dict.items():
                        form.add_error(field if field in form.fields else None, errors)
                else:
                    form.add_error(None, exc)
            else:
                messages.success(request, 'Membre créé.')
                return redirect('accounts:team')
    members = list(_team_queryset())
    for member in members:
        member.can_be_deleted = can_delete_team_member(request.user, member)
    archived_members = list(get_user_model().objects.filter(
        profile__deleted_at__isnull=False,
    ).select_related('profile').order_by('profile__full_name'))
    archived_members = [member for member in archived_members if can_delete_team_member(request.user, member)]
    return render(request, 'accounts/team.html', {
        'team_members': members, 'archived_members': archived_members, 'form': form,
    })


@login_required
@calendar_manager_required
def team_member_page(request, user_id):
    member = get_object_or_404(
        _team_queryset(), id=user_id
    )
    initial = {
        'full_name': member.profile.full_name,
        'email': member.profile.email,
        'role': member.profile.role,
        'calendar_color': member.profile.calendar_color,
        'is_active': member.is_active and member.profile.is_active,
    }
    form = TeamMemberEditForm(request.POST or None, initial=initial)
    if request.method == 'POST':
        if request.user.profile.role != Profile.Role.ADMIN:
            raise PermissionDenied
        if form.is_valid():
            try:
                update_user_account(
                    actor=request.user, user=member, data=form.cleaned_data
                )
            except ValidationError as exc:
                for field, errors in exc.message_dict.items():
                    for error in errors:
                        form.add_error(field, error)
            else:
                messages.success(request, 'Membre mis à jour.')
                return redirect('accounts:team-member', user_id=member.id)
    appointments = member.appointments.filter(
        deleted_at__isnull=True, start_at__gte=timezone.now()
    ).exclude(status=Appointment.Status.CANCELLED).select_related(
        'appointment_type', 'client'
    ).order_by('start_at')[:10]
    return render(
        request, 'accounts/team_member.html',
        {
            'member': member, 'form': form, 'upcoming_appointments': appointments,
            'can_delete_member': can_delete_team_member(request.user, member),
        },
    )


@require_http_methods(['GET', 'POST'])
@login_required
@calendar_manager_required
def team_member_delete_page(request, user_id):
    member = get_object_or_404(
        get_user_model().objects.select_related('profile'), id=user_id,
    )
    if not can_delete_team_member(request.user, member):
        raise PermissionDenied
    if request.method == 'POST':
        if request.POST.get('confirm') != 'yes':
            return render(
                request, 'accounts/team_member_delete.html',
                {'member': member, 'confirmation_error': True}, status=400,
            )
        delete_team_member(actor=request.user, user=member)
        messages.success(
            request,
            f'{member.profile.full_name} a été supprimé définitivement. '
            'Son adresse e-mail est disponible. Ses rendez-vous et l’historique sont conservés.',
        )
        return redirect('accounts:team')
    return render(request, 'accounts/team_member_delete.html', {'member': member})


def _team_payload(user):
    return {'id': user.id, 'full_name': user.profile.full_name, 'email': user.profile.email, 'role': user.profile.role, 'calendar_color': user.profile.calendar_color, 'is_active': user.is_active and user.profile.is_active}


@require_GET
@calendar_manager_required
def team_api(request):
    users = _team_queryset()
    return JsonResponse({'data': [_team_payload(user) for user in users]})


@require_http_methods(['POST'])
@admin_required
def team_create_api(request):
    try:
        data = json.loads(request.body or b'{}')
        if not isinstance(data, dict):
            raise ValidationError('Le corps JSON doit être un objet.')
        user = create_user_account(
            email=data.get('email', ''), password=data.get('password', ''),
            full_name=data.get('full_name', ''),
            role=data.get('role', Profile.Role.MEMBER),
            calendar_color=data.get('calendar_color'),
            actor=request.user,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        return JsonResponse({'error': 'validation_error', 'details': exc.message_dict if hasattr(exc, 'message_dict') else str(exc)}, status=400)
    return JsonResponse({'data': _team_payload(user)}, status=201)


@require_http_methods(['GET', 'PATCH'])
@calendar_manager_required
def team_detail_api(request, user_id):
    user = get_object_or_404(_team_queryset(), id=user_id)
    if request.method == 'PATCH':
        if request.user.profile.role != Profile.Role.ADMIN:
            raise PermissionDenied
        try:
            data = json.loads(request.body or b'{}')
            if not isinstance(data, dict):
                raise ValidationError('Le corps JSON doit être un objet.')
            update_user_account(actor=request.user, user=user, data=data)
        except (json.JSONDecodeError, ValidationError) as exc:
            return JsonResponse({'error': 'validation_error', 'details': exc.message_dict if hasattr(exc, 'message_dict') else str(exc)}, status=400)
    return JsonResponse({'data': _team_payload(user)})


@login_required
def settings_page(request):
    action = request.POST.get('action', '') if request.method == 'POST' else ''
    agency_settings = AgencySettings.load()
    profile_form = ProfileSettingsForm(
        request.POST if action == 'profile' else None,
        instance=request.user.profile,
    )
    password_form = PasswordChangeForm(
        request.user,
        request.POST if action == 'password' else None,
    )
    notification_form = NotificationSettingsForm(
        request.POST if action == 'notifications' else None,
        instance=request.user.profile,
    )
    agency_form = AgencySettingsForm(
        request.POST if action == 'agency' else None,
        instance=agency_settings,
    )
    appointment_type_form = AppointmentTypeSettingsForm(
        request.POST if action == 'type_create' else None
    )

    if request.method == 'POST':
        if action == 'profile' and profile_form.is_valid():
            old_values = {
                'full_name': request.user.profile.full_name,
                'email': request.user.profile.email,
                'calendar_color': request.user.profile.calendar_color,
                'avatar_url': request.user.profile.avatar_url,
            }
            profile = profile_form.save()
            log_activity(
                actor=request.user, action='profile_updated', entity_type='profile',
                entity_id=profile.id, old_values=old_values,
                new_values={key: getattr(profile, key) for key in old_values},
            )
            messages.success(request, 'Profil mis à jour.')
            return redirect('accounts:settings')
        if action == 'password' and password_form.is_valid():
            user = password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Mot de passe mis à jour.')
            return redirect('accounts:settings')
        if action == 'notifications' and notification_form.is_valid():
            notification_form.save()
            messages.success(request, 'Préférences de notification mises à jour.')
            return redirect('accounts:settings')
        if action == 'agency':
            if request.user.profile.role != Profile.Role.ADMIN:
                raise PermissionDenied
            if agency_form.is_valid():
                record = agency_form.save(commit=False)
                record.updated_by = request.user
                record.save()
                log_activity(
                    actor=request.user, action='agency_settings_updated',
                    entity_type='agency_settings', entity_id=record.pk,
                    new_values=agency_form.cleaned_data,
                )
                messages.success(request, 'Paramètres de l’agence mis à jour.')
                return redirect('accounts:settings')
        if action in {'type_create', 'type_rename', 'type_toggle'}:
            if not request.user.profile.can_manage_calendar:
                raise PermissionDenied
            if action == 'type_create' and appointment_type_form.is_valid():
                appointment_type = appointment_type_form.save(commit=False)
                appointment_type.created_by = request.user
                appointment_type.save()
                log_activity(
                    actor=request.user, action='appointment_type_created',
                    entity_type='appointment_type', entity_id=appointment_type.id,
                    new_values={'name': appointment_type.name, 'is_active': True},
                )
                messages.success(request, 'Type de rendez-vous ajouté.')
                return redirect('accounts:settings')
            if action == 'type_rename':
                appointment_type = get_object_or_404(
                    AppointmentType, id=request.POST.get('type_id')
                )
                edit_form = AppointmentTypeSettingsForm(
                    request.POST, instance=appointment_type
                )
                if edit_form.is_valid():
                    appointment_type = edit_form.save()
                    log_activity(
                        actor=request.user, action='appointment_type_updated',
                        entity_type='appointment_type', entity_id=appointment_type.id,
                        new_values={
                            'name': appointment_type.name,
                            'is_active': appointment_type.is_active,
                        },
                    )
                    messages.success(request, 'Type de rendez-vous renommé.')
                    return redirect('accounts:settings')
                appointment_type_form = edit_form
            if action == 'type_toggle':
                appointment_type = get_object_or_404(
                    AppointmentType, id=request.POST.get('type_id')
                )
                appointment_type.is_active = not appointment_type.is_active
                appointment_type.save(update_fields=('is_active', 'updated_at'))
                log_activity(
                    actor=request.user, action='appointment_type_updated',
                    entity_type='appointment_type', entity_id=appointment_type.id,
                    new_values={'name': appointment_type.name, 'is_active': appointment_type.is_active},
                )
                messages.success(request, 'État du type mis à jour.')
                return redirect('accounts:settings')

    return render(
        request,
        'accounts/settings.html',
        {
            'profile_form': profile_form,
            'password_form': password_form,
            'notification_form': notification_form,
            'agency_form': agency_form,
            'appointment_type_form': appointment_type_form,
            'appointment_types': AppointmentType.objects.all(),
            'agency_settings': agency_settings,
        },
    )
