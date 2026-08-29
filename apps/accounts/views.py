from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .forms import EmailAuthenticationForm
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
