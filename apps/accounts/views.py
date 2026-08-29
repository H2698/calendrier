from datetime import timedelta
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from .forms import EmailAuthenticationForm, TeamMemberForm
from .models import Profile
from .permissions import admin_required, calendar_manager_required
from .services import create_user_account, set_account_active
from apps.calendar_app.models import Appointment


class AgencyLoginView(LoginView):
    authentication_form = EmailAuthenticationForm
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    data = _dashboard_data(request.user)
    return render(request, 'dashboard.html', data)


def _dashboard_data(user):
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


@login_required
@calendar_manager_required
def team_page(request):
    form = TeamMemberForm(request.POST or None)
    if request.method == 'POST':
        if request.user.profile.role != Profile.Role.ADMIN:
            raise PermissionDenied
        if form.is_valid():
            create_user_account(**form.cleaned_data)
            return redirect('accounts:team')
    members = get_user_model().objects.select_related('profile').order_by('profile__full_name')
    return render(request, 'accounts/team.html', {'team_members': members, 'form': form})


def _team_payload(user):
    return {'id': user.id, 'full_name': user.profile.full_name, 'email': user.profile.email, 'role': user.profile.role, 'calendar_color': user.profile.calendar_color, 'is_active': user.is_active and user.profile.is_active}


@require_GET
@calendar_manager_required
def team_api(request):
    users = get_user_model().objects.select_related('profile').order_by('profile__full_name')
    return JsonResponse({'data': [_team_payload(user) for user in users]})


@require_http_methods(['POST'])
@admin_required
def team_create_api(request):
    try:
        data = json.loads(request.body or b'{}')
        user = create_user_account(email=data.get('email', ''), password=data.get('password', ''), full_name=data.get('full_name', ''), role=data.get('role', Profile.Role.MEMBER), calendar_color=data.get('calendar_color', '#2563EB'))
    except (json.JSONDecodeError, ValidationError) as exc:
        return JsonResponse({'error': 'validation_error', 'details': exc.message_dict if hasattr(exc, 'message_dict') else str(exc)}, status=400)
    return JsonResponse({'data': _team_payload(user)}, status=201)


@require_http_methods(['GET', 'PATCH'])
@calendar_manager_required
def team_detail_api(request, user_id):
    user = get_object_or_404(get_user_model().objects.select_related('profile'), id=user_id)
    if request.method == 'PATCH':
        if request.user.profile.role != Profile.Role.ADMIN:
            raise PermissionDenied
        try:
            data = json.loads(request.body or b'{}')
            for field in ('full_name', 'role', 'calendar_color'):
                if field in data:
                    setattr(user.profile, field, data[field])
            user.profile.full_clean(); user.profile.save()
            if 'is_active' in data:
                set_account_active(user=user, is_active=bool(data['is_active']))
        except (json.JSONDecodeError, ValidationError) as exc:
            return JsonResponse({'error': 'validation_error', 'details': exc.message_dict if hasattr(exc, 'message_dict') else str(exc)}, status=400)
    return JsonResponse({'data': _team_payload(user)})
